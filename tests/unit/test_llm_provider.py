"""Unit tests for the LLM provider layer's JSON handling.

The complete_json fallback is the piece that keeps structured passes (KG
extraction, pre-pass, memory update) working on any OpenAI-compatible server,
so its parsing paths get direct coverage here without any network calls.
"""

import pytest
from pydantic import BaseModel

from ragline.llm.base import BaseLLM


class _Result(BaseModel):
    """Tiny schema standing in for real structured-pass results."""

    mode: str
    score: int


class _FakeLLM(BaseLLM):
    """BaseLLM with a canned complete() so we can exercise the default
    complete_json() fence-stripping parse path."""

    def __init__(self, canned: str):
        # The exact text complete() will return.
        self.canned = canned

    async def complete(self, messages, temperature=0.0):
        return self.canned

    async def stream(self, messages, temperature=0.0):  # pragma: no cover - unused
        yield self.canned


async def test_complete_json_plain():
    """Bare JSON parses and validates."""
    llm = _FakeLLM('{"mode": "rag", "score": 7}')
    result = await llm.complete_json([], _Result)
    assert result.mode == "rag"
    assert result.score == 7


async def test_complete_json_fenced():
    """JSON wrapped in ```json fences (common LLM habit) still parses."""
    llm = _FakeLLM('```json\n{"mode": "library", "score": 3}\n```')
    result = await llm.complete_json([], _Result)
    assert result.mode == "library"


async def test_complete_json_invalid_raises():
    """Non-JSON output surfaces as an error rather than silent garbage."""
    llm = _FakeLLM("sorry, I cannot do that")
    with pytest.raises(Exception):
        await llm.complete_json([], _Result)
