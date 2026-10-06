"""OpenAIProvider — chat completions against ONE OpenAI-compatible endpoint.

Replaces raggles' LiteLLMProvider. LiteLLM's multi-provider translation was
unused under ragline's single-endpoint constraint, so we use the official
`openai` SDK directly: AsyncOpenAI(base_url=...) works identically against
OpenAI cloud, Azure's OpenAI-compatible endpoint, RunPod-hosted vLLM, and
on-prem vLLM. Migrating between them is an env-var change only.

Kept from raggles verbatim:
  * tenacity retry policy (3 attempts, exponential backoff 1-10s),
  * token accumulation into the ContextVar TraceCollector after every call.
Dropped: Anthropic cache_control injection (cloud-provider-specific).
Added: a fallback in complete_json for servers that reject response_format.
"""

from collections.abc import AsyncIterator
from typing import TypeVar

import structlog
from openai import AsyncOpenAI, BadRequestError
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from ragline.config import settings
from ragline.llm.base import BaseLLM
from ragline.tracing.collector import get_current_trace

log = structlog.get_logger()

T = TypeVar("T", bound=BaseModel)


def _record_usage(usage) -> None:
    """Add a response's token usage to the current request's trace collector.

    Called after every completion. Because ALL LLM passes in a turn go through
    this provider, whole-turn totals accumulate automatically (see tracing/).
    """
    # Look up the collector registered for this request context (None when
    # called outside a traced request, e.g. from a script).
    trace = get_current_trace()
    if trace and usage:
        # `or 0` guards against servers that omit individual usage fields.
        trace.prompt_tokens += usage.prompt_tokens or 0
        trace.completion_tokens += usage.completion_tokens or 0


class OpenAIProvider(BaseLLM):
    """BaseLLM implementation over the `openai` SDK with a configurable base_url."""

    def __init__(self, model: str):
        # Model name exactly as the server knows it (e.g. "gpt-4o" on OpenAI,
        # "Qwen/Qwen2.5-72B-Instruct" on a vLLM host).
        self.model = model
        # One async client for the process; base_url/api_key come from config.
        # An empty key becomes a placeholder: the SDK refuses to construct
        # without one, but key-less local servers (vLLM) ignore it entirely —
        # servers that DO need auth will reject at call time with a clear 401.
        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "not-needed",
        )
        # Set to False the first time the server rejects response_format, so
        # we don't pay a failed round-trip on every JSON call thereafter.
        self._server_supports_json_mode = True

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def complete(
        self, messages: list[dict], temperature: float = 0.0, max_tokens: int | None = None
    ) -> str:
        """One chat completion; returns the assistant message text."""
        # Only send max_tokens when a caller asked for a ceiling — omitting the
        # key entirely lets the server apply its own default, which is what
        # every caller except knowledge-graph extraction wants.
        extra: dict = {"max_tokens": max_tokens} if max_tokens is not None else {}
        # Standard OpenAI-compatible chat completion call.
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            **extra,
        )
        # First (only) choice carries the answer text.
        text = response.choices[0].message.content or ""
        log.debug("llm completion", model=self.model, tokens=getattr(response.usage, "total_tokens", None))
        # A ceiling hit is otherwise invisible: the answer just stops (and a RAG
        # answer can lose its last citation). Log it so the ceiling can be tuned.
        if getattr(response.choices[0], "finish_reason", None) == "length":
            log.warning("llm completion truncated at output ceiling", model=self.model,
                        max_tokens=max_tokens,
                        completion_tokens=getattr(response.usage, "completion_tokens", None))
        # Accumulate token usage into the current trace.
        _record_usage(response.usage)
        return text

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def complete_json(
        self, messages: list[dict], response_model: type[T], temperature: float = 0.0
    ) -> T:
        """Chat completion that must return JSON matching `response_model`.

        Preferred path: native JSON mode via response_format={"type":
        "json_object"} — supported by OpenAI and vLLM. Fallback path: if the
        server rejects the parameter (BadRequestError), permanently switch to
        plain completions + fence-stripping JSON parse (BaseLLM default).
        This keeps graph extraction / pre-pass / memory passes working on ANY
        OpenAI-compatible server.
        """
        # Fallback path — server previously rejected response_format.
        if not self._server_supports_json_mode:
            return await super().complete_json(messages, response_model, temperature=temperature)
        try:
            # Native JSON-mode completion.
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
        except BadRequestError:
            # Server doesn't implement response_format — remember that and
            # answer this call via the fallback parse instead.
            log.warning("server rejected response_format; falling back to plain JSON parsing",
                        model=self.model)
            self._server_supports_json_mode = False
            return await super().complete_json(messages, response_model, temperature=temperature)
        # Extract, account, validate — same shape as complete().
        text = response.choices[0].message.content or ""
        log.debug("llm json completion", model=self.model, tokens=getattr(response.usage, "total_tokens", None))
        _record_usage(response.usage)
        # Validate the JSON text straight into the pydantic model.
        return response_model.model_validate_json(text)

    async def stream(self, messages: list[dict], temperature: float = 0.0) -> AsyncIterator[str]:
        """Streaming chat completion, yielding text deltas as they arrive.

        stream_options.include_usage asks compliant servers to append a final
        chunk carrying token usage so streamed turns are still accounted.
        """
        # Open the streaming completion.
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            stream=True,
            stream_options={"include_usage": True},
        )
        # Relay each delta's text to the caller as it arrives.
        async for chunk in stream:
            # The final usage chunk has no choices — capture its token counts.
            if not chunk.choices:
                _record_usage(getattr(chunk, "usage", None))
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
