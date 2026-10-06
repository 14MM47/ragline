"""Qwen3-Embedding query instruction — applied to queries only, never documents.

Qwen3-Embedding expects retrieval queries as "Instruct: {task}\nQuery:{query}"
(no space after "Query:") while documents stay raw. The knowledge-graph entity
lookup opts out with instruction="" because its cosine threshold was
calibrated on raw-vs-raw scores.
"""

import asyncio

import numpy as np

from ragline.config import settings
from ragline.embeddings.openai_embedder import OpenAIEmbedder

INSTR = "Given a question, retrieve passages that answer it"


def _embedder(monkeypatch) -> tuple[OpenAIEmbedder, list[list[str]]]:
    """An embedder whose network batch call is replaced by a recorder."""
    sent: list[list[str]] = []
    emb = OpenAIEmbedder("m")

    async def fake_batch(batch: list[str]) -> list[list[float]]:
        # Record exactly what would have gone over the wire.
        sent.append(list(batch))
        return [[1.0, 0.0] for _ in batch]

    monkeypatch.setattr(emb, "_embed_batch", fake_batch)
    return emb, sent


def test_query_prefixed_when_instruction_configured(monkeypatch):
    monkeypatch.setattr(settings, "embedding_query_instruction", INSTR)
    emb, sent = _embedder(monkeypatch)
    asyncio.run(emb.embed_query("rated voltage of X20DI9371?"))
    assert sent == [[f"Instruct: {INSTR}\nQuery:rated voltage of X20DI9371?"]]


def test_documents_never_prefixed(monkeypatch):
    monkeypatch.setattr(settings, "embedding_query_instruction", INSTR)
    emb, sent = _embedder(monkeypatch)
    asyncio.run(emb.embed(["chunk a", "chunk b"]))
    assert sent == [["chunk a", "chunk b"]]


def test_empty_setting_leaves_query_raw(monkeypatch):
    """Default (empty) = today's behaviour, e.g. for OpenAI embeddings."""
    monkeypatch.setattr(settings, "embedding_query_instruction", "")
    emb, sent = _embedder(monkeypatch)
    asyncio.run(emb.embed_query("q"))
    assert sent == [["q"]]


def test_explicit_empty_instruction_overrides_setting(monkeypatch):
    monkeypatch.setattr(settings, "embedding_query_instruction", INSTR)
    emb, sent = _embedder(monkeypatch)
    asyncio.run(emb.embed_query("q", instruction=""))
    assert sent == [["q"]]


def test_kg_entity_lookup_uses_raw_query(monkeypatch):
    """find_entities must embed the query WITHOUT the retrieval instruction."""
    from ragline.knowledge_graph.graph_index import GraphIndex

    monkeypatch.setattr(settings, "embedding_query_instruction", INSTR)
    emb, sent = _embedder(monkeypatch)
    idx = GraphIndex.__new__(GraphIndex)
    # Minimal state: one entity whose embedding matches the fake query vector.
    idx._entities = {"e1": object()}
    idx._entity_embeddings = {"e1": np.array([1.0, 0.0], dtype=np.float32)}
    found = asyncio.run(idx.find_entities("X20DI9371", emb))
    assert sent == [["X20DI9371"]]
    assert len(found) == 1
