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

import time
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

# Clock for the slow-call log (a module name of its own so tests can fake it
# without touching the process-wide time.monotonic that asyncio relies on).
_now = time.monotonic

T = TypeVar("T", bound=BaseModel)


def _merge_body(base: dict, over: dict) -> dict:
    """`over` merged onto `base`, one level deep for nested objects.

    So {"chat_template_kwargs": {"enable_thinking": true}} over a base that
    also sets other chat_template_kwargs keeps those keys and flips only this one.
    """
    merged = dict(base)
    for key, value in over.items():
        # Two objects under the same key combine; anything else is replaced.
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _extra_body_kw(answer: bool = False) -> dict:
    """The `extra_body=` keyword for a completion call, or nothing.

    Read from settings on every call (not cached at construction) so the
    evaluation harness can flip a hybrid model's thinking mode between runs
    without rebuilding the provider. An answer call (answer=True) also gets
    ANSWER_EXTRA_BODY merged on top. Empty settings = the key is omitted
    entirely, so production requests are byte-for-byte what they were.
    """
    body = settings.llm_extra_body_dict
    if answer and settings.answer_extra_body_dict:
        body = _merge_body(body, settings.answer_extra_body_dict)
    return {"extra_body": body} if body else {}


def _record_reasoning(message_or_delta) -> str | None:
    """Count a response's hidden reasoning text on the current trace.

    vLLM started with --reasoning-parser keeps a thinking model's reasoning OUT
    of `content`, in a field outside the OpenAI schema (so read via getattr):
    `reasoning` in current vLLM, `reasoning_content` in older releases — both
    are checked. We record only its length: the text itself is never stored
    and never reaches the answer or citations.
    """
    trace = get_current_trace()
    reasoning = (getattr(message_or_delta, "reasoning", None)
                 or getattr(message_or_delta, "reasoning_content", None))
    # Only text counts (a non-string value would be a server change, not reasoning).
    if not isinstance(reasoning, str):
        reasoning = None
    if trace and reasoning:
        trace.reasoning_chars += len(reasoning)
    # Returned so a call record can keep the text when transcripts are on.
    return reasoning


def _warn_if_slow(started: float, purpose: str, model: str, max_tokens: int | None, usage) -> None:
    """Log a call that took longer than LLM_SLOW_CALL_S, naming what it was for."""
    elapsed = _now() - started
    if settings.llm_slow_call_s and elapsed > settings.llm_slow_call_s:
        log.warning("slow llm call", purpose=purpose or "unspecified", seconds=round(elapsed, 1),
                    model=model, max_tokens=max_tokens,
                    completion_tokens=getattr(usage, "completion_tokens", None))


def _record_call(*, purpose: str, answer: bool, usage, ms: float, finish_reason, max_tokens: int | None,
                 temperature: float, reasoning: str | None, messages: list[dict], response: str,
                 ttft_ms: float | None = None, json_valid: bool | None = None) -> None:
    """Append one model call's record to the current trace (see TraceCollector.calls).

    Numbers always; the text (messages sent, response, reasoning) only with
    LLM_CAPTURE_TRANSCRIPTS on — evaluation runs, never production by default.
    """
    trace = get_current_trace()
    if not trace:
        return
    completion = getattr(usage, "completion_tokens", None) if usage else None
    entry = {
        # What the call was for, and whether answer-only options applied.
        "purpose": purpose or ("answer" if answer else ""), "answer": answer,
        # Tokens each way and the separated reasoning length.
        "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
        "completion_tokens": completion,
        "reasoning_chars": len(reasoning) if reasoning else 0,
        # Wall time of the request and the end-to-end output rate (includes prefill).
        "ms": round(ms, 1),
        "tok_s": round(completion / (ms / 1000), 1) if completion and ms > 0 else None,
        "ttft_ms": round(ttft_ms, 1) if ttft_ms is not None else None,
        # How it ended and under which settings.
        "finish_reason": finish_reason, "max_tokens": max_tokens, "temperature": temperature,
    }
    if json_valid is not None:
        # JSON-mode calls: whether the reply validated. A failed one is retried, and
        # each attempt is a real call that used tokens, so each gets its own record.
        entry["json_valid"] = json_valid
    if settings.llm_capture_transcripts:
        # Full exchange, for the evaluation transcript sidecar.
        entry.update({"messages": messages, "response": response, "reasoning": reasoning or ""})
    trace.add_call(entry)


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
        self, messages: list[dict], temperature: float = 0.0, max_tokens: int | None = None,
        answer: bool = False, purpose: str = "",
    ) -> str:
        """One chat completion; returns the assistant message text.

        answer=True marks an answer-generation call, which also gets
        ANSWER_EXTRA_BODY (e.g. thinking on for answers only).
        """
        # Only send max_tokens when a caller asked for a ceiling — omitting the
        # key entirely lets the server apply its own default, which is what
        # every caller except knowledge-graph extraction wants.
        extra: dict = {"max_tokens": max_tokens} if max_tokens is not None else {}
        # An answer call may run at its own temperature (ANSWER_TEMPERATURE, e.g.
        # a thinking model's recommended sampling); every other call keeps the caller's.
        if answer and settings.answer_temperature is not None:
            temperature = settings.answer_temperature
        # Timed so a slow call can be named in the log (purpose = what it was for).
        started = _now()
        # Standard OpenAI-compatible chat completion call.
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            **extra,
            **_extra_body_kw(answer),
        )
        # First (only) choice carries the answer text; any reasoning the
        # server separated out is counted, not returned.
        text = response.choices[0].message.content or ""
        reasoning = _record_reasoning(response.choices[0].message)
        log.debug("llm completion", model=self.model, tokens=getattr(response.usage, "total_tokens", None))
        # A ceiling hit is otherwise invisible: the answer just stops (and a RAG
        # answer can lose its last citation). Log it so the ceiling can be tuned.
        if getattr(response.choices[0], "finish_reason", None) == "length":
            log.warning("llm completion truncated at output ceiling", model=self.model,
                        max_tokens=max_tokens,
                        completion_tokens=getattr(response.usage, "completion_tokens", None))
        _warn_if_slow(started, purpose or ("answer" if answer else ""), self.model, max_tokens, response.usage)
        # One record per call: purpose, tokens each way, time, finish reason (+ text if capturing).
        _record_call(purpose=purpose, answer=answer, usage=response.usage, ms=(_now() - started) * 1000,
                     finish_reason=getattr(response.choices[0], "finish_reason", None),
                     max_tokens=max_tokens, temperature=temperature, reasoning=reasoning,
                     messages=messages, response=text)
        # Accumulate token usage into the current trace.
        _record_usage(response.usage)
        return text

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def complete_json(
        self, messages: list[dict], response_model: type[T], temperature: float = 0.0,
        max_tokens: int | None = None, purpose: str = "",
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
            return await super().complete_json(messages, response_model, temperature=temperature,
                                               max_tokens=max_tokens, purpose=purpose or "json")
        # Optional output ceiling (JSON mode can degenerate into endless output).
        extra: dict = {"max_tokens": max_tokens} if max_tokens is not None else {}
        started = _now()
        try:
            # Native JSON-mode completion.
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
                **extra,
                **_extra_body_kw(),
            )
        except BadRequestError:
            # Server doesn't implement response_format — remember that and
            # answer this call via the fallback parse instead.
            log.warning("server rejected response_format; falling back to plain JSON parsing",
                        model=self.model)
            self._server_supports_json_mode = False
            return await super().complete_json(messages, response_model, temperature=temperature,
                                               max_tokens=max_tokens, purpose=purpose or "json")
        # Extract, account, validate — same shape as complete().
        text = response.choices[0].message.content or ""
        reasoning = _record_reasoning(response.choices[0].message)
        log.debug("llm json completion", model=self.model, tokens=getattr(response.usage, "total_tokens", None))
        # A ceiling hit means the JSON is cut off and will fail validation below: say so.
        if getattr(response.choices[0], "finish_reason", None) == "length":
            log.warning("llm json completion truncated at output ceiling", model=self.model,
                        purpose=purpose or "unspecified", max_tokens=max_tokens)
        _warn_if_slow(started, purpose or "json", self.model, max_tokens, response.usage)
        ms = (_now() - started) * 1000
        _record_usage(response.usage)
        # Validate the JSON text straight into the pydantic model; the call is
        # recorded either way, flagged with whether its reply validated.
        try:
            result = response_model.model_validate_json(text)
        except Exception:
            _record_call(purpose=purpose or "json", answer=False, usage=response.usage, ms=ms,
                         finish_reason=getattr(response.choices[0], "finish_reason", None),
                         max_tokens=max_tokens, temperature=temperature, reasoning=reasoning,
                         messages=messages, response=text, json_valid=False)
            raise
        _record_call(purpose=purpose or "json", answer=False, usage=response.usage, ms=ms,
                     finish_reason=getattr(response.choices[0], "finish_reason", None),
                     max_tokens=max_tokens, temperature=temperature, reasoning=reasoning,
                     messages=messages, response=text, json_valid=True)
        return result

    async def stream(self, messages: list[dict], temperature: float = 0.0) -> AsyncIterator[str]:
        """Streaming chat completion, yielding text deltas as they arrive.

        stream_options.include_usage asks compliant servers to append a final
        chunk carrying token usage so streamed turns are still accounted.
        """
        # Timed: first-token latency and total time go on the call record.
        started = _now()
        first_token_at: float | None = None
        parts: list[str] = []                 # response text, kept only for the record
        reasoning_parts: list[str] = []       # reasoning text, likewise
        usage = None
        finish_reason = None
        # Open the streaming completion.
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            stream=True,
            stream_options={"include_usage": True},
            **_extra_body_kw(),
        )
        # Relay each delta's text to the caller as it arrives.
        async for chunk in stream:
            # The final usage chunk has no choices — capture its token counts.
            if not chunk.choices:
                usage = getattr(chunk, "usage", None)
                _record_usage(usage)
                continue
            # Reasoning deltas arrive on the same stream (when the server
            # separates them); count them, never relay them.
            piece = _record_reasoning(chunk.choices[0].delta)
            if piece:
                reasoning_parts.append(piece)
            finish_reason = getattr(chunk.choices[0], "finish_reason", None) or finish_reason
            delta = chunk.choices[0].delta.content
            if delta:
                # First visible token: the time-to-first-token mark.
                if first_token_at is None:
                    first_token_at = _now()
                parts.append(delta)
                yield delta
        # The whole streamed call as one record (TTFT included).
        _record_call(purpose="stream", answer=False, usage=usage, ms=(_now() - started) * 1000,
                     finish_reason=finish_reason, max_tokens=None, temperature=temperature,
                     reasoning="".join(reasoning_parts) or None, messages=messages, response="".join(parts),
                     ttft_ms=(first_token_at - started) * 1000 if first_token_at is not None else None)
