"""BaseLLM — the abstract interface every LLM provider implements.

Ported verbatim (plus comments) from raggles. Keeping the exact same three
methods (complete / stream / complete_json) means every raggles call site —
RAG agent, chat agent, KG extractor, pre-pass, confidence scorer — ports to
ragline without modification.
"""

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TypeVar

from pydantic import BaseModel

# Any pydantic model type; complete_json validates the LLM's JSON against it.
T = TypeVar("T", bound=BaseModel)


class BaseLLM(ABC):
    @abstractmethod
    async def complete(
        self, messages: list[dict], temperature: float = 0.0, max_tokens: int | None = None
    ) -> str:
        """Run one chat completion and return the assistant text.

        max_tokens is an optional output ceiling; None leaves it to the server
        (the default everywhere except knowledge-graph extraction, which caps it
        so one runaway generation cannot hold a concurrency slot indefinitely).
        """
        ...

    @abstractmethod
    async def stream(self, messages: list[dict], temperature: float = 0.0) -> AsyncIterator[str]:
        """Run one chat completion, yielding text deltas as they arrive."""
        ...

    async def complete_json(
        self, messages: list[dict], response_model: type[T], temperature: float = 0.0
    ) -> T:
        """Complete a chat request expecting JSON output, validated against a
        Pydantic model.

        Default implementation: calls complete(), strips any markdown fences,
        parses JSON, validates with Pydantic. Subclasses override this to use
        the server's native JSON mode (response_format) when available.
        """
        # Get the raw completion text.
        raw = await self.complete(messages, temperature=temperature)
        # Models sometimes wrap JSON in ```json ... ``` fences — strip them.
        stripped = raw.strip()
        if stripped.startswith("```"):
            # Drop the opening fence line (``` or ```json).
            stripped = stripped.split("\n", 1)[-1]
            # Drop the closing fence if present.
            if stripped.endswith("```"):
                stripped = stripped[:-3].strip()
        # Parse and validate against the requested model.
        data = json.loads(stripped)
        return response_model.model_validate(data)
