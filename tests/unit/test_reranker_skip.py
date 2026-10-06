"""Reranker score-gap skip: dominance is judged on dense cosine scores and
only acted on when RRF kept the dominant chunk at rank 1.

Adapted from raggles (the trace-flag assertion is gone — ragline's minimal
trace no longer records reranker skips).
"""

from ragline.chunking.models import Chunk
from ragline.config import settings
from ragline.retrieval.pipeline import RetrievalPipeline
from ragline.vectorstore.base import SearchResult


class _StubReranker:
    """Records whether rerank() was invoked."""

    def __init__(self):
        self.called = False

    async def rerank(self, query, results, top_k=8):
        self.called = True
        return results[:top_k]


def _chunk(idx: int, doc: str = "doc-1") -> Chunk:
    return Chunk(
        text=f"chunk {idx}",
        source_file="test.pdf",
        document_id=doc,
        page_start=1,
        page_end=1,
        char_start=idx * 100,
        char_end=idx * 100 + 10,
        chunk_index=idx,
        chunk_id=f"{doc}-{idx}",
    )


def _pipeline(monkeypatch) -> tuple[RetrievalPipeline, _StubReranker]:
    """Pipeline with the real CrossEncoder load suppressed, stub injected."""
    # provider "none" prevents the ~2GB model download in unit tests.
    monkeypatch.setattr(settings, "reranker_provider", "none")
    pipeline = RetrievalPipeline(vector_store=None, embedder=None)
    stub = _StubReranker()
    pipeline._reranker = stub
    return pipeline, stub


def _dense_dominant() -> list[SearchResult]:
    # gap = 0.9 - mean(0.4, 0.3, 0.2) = 0.6 > 0.25; top 0.9 > 0.5.
    return [
        SearchResult(chunk=_chunk(0), score=0.9),
        SearchResult(chunk=_chunk(1), score=0.4),
        SearchResult(chunk=_chunk(2), score=0.3),
        SearchResult(chunk=_chunk(3), score=0.2),
    ]


def _rrf_scored(order: list[SearchResult]) -> list[SearchResult]:
    """Re-score a list on the RRF scale (max ~1/61) preserving order."""
    return [
        SearchResult(chunk=r.chunk, score=1.0 / (61 + rank))
        for rank, r in enumerate(order)
    ]


async def test_skip_fires_when_dense_dominant_and_fusion_agrees(monkeypatch):
    pipeline, stub = _pipeline(monkeypatch)
    dense = _dense_dominant()
    merged = _rrf_scored(dense)  # RRF scores, same head

    results = await pipeline._rerank("q", merged, rerank_k=2, dense_results=dense)

    assert not stub.called
    assert [r.chunk.chunk_id for r in results] == [merged[0].chunk.chunk_id, merged[1].chunk.chunk_id]


async def test_no_skip_when_fusion_disagrees_on_top_chunk(monkeypatch):
    pipeline, stub = _pipeline(monkeypatch)
    dense = _dense_dominant()
    # BM25 pushed a different chunk to the top of the fused list.
    merged = _rrf_scored([dense[1], dense[0], dense[2], dense[3]])

    await pipeline._rerank("q", merged, rerank_k=2, dense_results=dense)

    assert stub.called


async def test_no_skip_when_dense_not_dominant(monkeypatch):
    pipeline, stub = _pipeline(monkeypatch)
    dense = [
        SearchResult(chunk=_chunk(0), score=0.55),
        SearchResult(chunk=_chunk(1), score=0.5),
        SearchResult(chunk=_chunk(2), score=0.45),
    ]
    merged = _rrf_scored(dense)

    await pipeline._rerank("q", merged, rerank_k=2, dense_results=dense)

    assert stub.called


async def test_rrf_scores_alone_never_trigger_skip(monkeypatch):
    """Without dense scores the check falls back to merged; RRF's scale
    (max ~2/61) can never clear the cosine-calibrated thresholds."""
    pipeline, stub = _pipeline(monkeypatch)
    merged = _rrf_scored(_dense_dominant())

    await pipeline._rerank("q", merged, rerank_k=2, dense_results=None)

    assert stub.called


async def test_dense_only_regime_unchanged(monkeypatch):
    """When BM25 returns nothing, merged IS the dense list, and a dominant
    top result still skips the cross-encoder."""
    pipeline, stub = _pipeline(monkeypatch)
    dense = _dense_dominant()

    results = await pipeline._rerank("q", dense, rerank_k=2, dense_results=dense)

    assert not stub.called
    assert len(results) == 2
