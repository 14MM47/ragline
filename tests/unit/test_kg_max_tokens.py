"""Knowledge-graph extraction must cap its output tokens.

Extraction fires one LLM call per chunk — ~113k of them for the full corpus, at
96-way concurrency. Without a ceiling a single degenerate generation can run to
the model's whole context window and hold a concurrency slot for minutes. The
cap is configurable (kg_extraction_max_tokens) and must reach the provider; the
provider in turn must NOT send the key at all for ordinary calls, so servers
that dislike an explicit null are unaffected.
"""

import asyncio

from ragline.chunking.models import Chunk
from ragline.config import settings
from ragline.knowledge_graph.extractor import extract_entities_and_relationships
from ragline.llm.openai_provider import OpenAIProvider


class _RecordingLLM:
    """Stands in for BaseLLM, capturing the kwargs of each complete() call."""

    def __init__(self):
        self.calls: list[dict] = []

    async def complete(self, messages, temperature=0.0, max_tokens=None):
        self.calls.append({"temperature": temperature, "max_tokens": max_tokens})
        # Minimal well-formed extraction payload.
        return '{"entities": [], "relationships": []}'


def _chunk() -> Chunk:
    """One chunk, enough to trigger exactly one extraction call."""
    return Chunk(
        text="The M580 controller supports Modbus TCP over the X80 backplane.",
        source_file="plc.pdf",
        document_id="doc-1",
        page_start=1,
        page_end=1,
        char_start=0,
        char_end=63,
        chunk_index=0,
        chunk_id="doc-1-0",
    )


def test_extraction_passes_configured_max_tokens():
    """The extractor must forward the configured cap on every call."""
    llm = _RecordingLLM()

    asyncio.run(extract_entities_and_relationships([_chunk()], llm, embedder=None))

    assert len(llm.calls) == 1
    assert llm.calls[0]["max_tokens"] == settings.kg_extraction_max_tokens
    # A cap that truncates legitimate output would silently lose entities.
    assert settings.kg_extraction_max_tokens >= 1024


def test_provider_omits_max_tokens_when_unset(monkeypatch):
    """Ordinary completions must not send a max_tokens key at all."""
    provider = OpenAIProvider("test-model")
    seen: list[dict] = []

    class _Usage:
        prompt_tokens = 1
        completion_tokens = 1

    class _Msg:
        content = "hello"

    class _Choice:
        message = _Msg()

    class _Response:
        choices = [_Choice()]
        usage = _Usage()

    async def fake_create(**kwargs):
        seen.append(kwargs)
        return _Response()

    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    asyncio.run(provider.complete([{"role": "user", "content": "hi"}]))
    assert "max_tokens" not in seen[0]

    asyncio.run(provider.complete([{"role": "user", "content": "hi"}], max_tokens=2048))
    assert seen[1]["max_tokens"] == 2048
