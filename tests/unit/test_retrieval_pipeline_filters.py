"""RetrievalPipeline filter behaviour with a fake vector store.

Adapted from raggles: ragline's pipeline requires search_filtered (server-side
filtering) rather than the progressive-fetch fallback, so these tests assert
that scoping options are passed through and that the empty-allow-list case
short-circuits without touching the store at all.
"""

from ragline.chunking.models import Chunk
from ragline.config import settings
from ragline.embeddings.base import BaseEmbedder
from ragline.retrieval.pipeline import RetrievalPipeline
from ragline.vectorstore.base import BaseVectorStore, SearchResult


class _DummyEmbedder(BaseEmbedder):
    """Fixed embedding — retrieval math is not under test here."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [0.1]


class _FakeVectorStore(BaseVectorStore):
    """Returns canned results and records the filters it was called with."""

    def __init__(self, ranked_results: list[SearchResult]):
        self._ranked_results = ranked_results
        self.calls: list[dict] = []

    async def upsert_chunks(self, chunks, embeddings) -> None:
        return None

    async def search_filtered(
        self,
        embedding,
        top_k: int = 10,
        allowed_document_ids=None,
        excluded_source_files=None,
    ) -> list[SearchResult]:
        # Record the scoping arguments for assertions.
        self.calls.append({
            "top_k": top_k,
            "allowed": allowed_document_ids,
            "excluded": excluded_source_files,
        })
        # Emulate server-side filtering.
        results = self._ranked_results
        if allowed_document_ids is not None:
            allowed = set(allowed_document_ids)
            results = [r for r in results if r.chunk.document_id in allowed]
        return results[:top_k]

    async def delete_by_document_id(self, document_id: str) -> None:
        return None

    async def get_all_chunks(self):
        return []

    async def ping(self, timeout: float = 2.0) -> bool:
        return True


def _result(document_id: str, source_file: str, score: float, idx: int) -> SearchResult:
    chunk = Chunk(
        text=f"chunk {idx}",
        source_file=source_file,
        document_id=document_id,
        page_start=1,
        page_end=1,
        char_start=idx * 100,
        char_end=(idx * 100) + 10,
        chunk_index=idx,
    )
    return SearchResult(chunk=chunk, score=score)


def _pipeline(store, monkeypatch) -> RetrievalPipeline:
    """Pipeline without the real reranker (no model download in unit tests)."""
    monkeypatch.setattr(settings, "reranker_provider", "none")
    return RetrievalPipeline(store, _DummyEmbedder())


async def test_allowed_document_filter_passed_through(monkeypatch):
    """The allow-list reaches the store and constrains the results."""
    ranked = [
        _result("blocked-a", "a.pdf", 0.99, 0),
        _result("blocked-b", "b.pdf", 0.98, 1),
        _result("allowed-doc", "allowed.pdf", 0.97, 2),
    ]
    store = _FakeVectorStore(ranked)
    pipeline = _pipeline(store, monkeypatch)

    results = await pipeline.retrieve(
        "find allowed content",
        top_k=5,
        allowed_document_ids=["allowed-doc"],
    )

    assert len(results) == 1
    assert results[0].chunk.document_id == "allowed-doc"
    assert store.calls[0]["allowed"] == ["allowed-doc"]


async def test_empty_allow_list_short_circuits(monkeypatch):
    """An explicitly empty allow-list returns [] without any search."""
    store = _FakeVectorStore([_result("doc", "x.pdf", 0.9, 0)])
    pipeline = _pipeline(store, monkeypatch)

    results = await pipeline.retrieve("anything", allowed_document_ids=[])

    assert results == []
    # The store must never have been queried.
    assert store.calls == []


async def test_exclusions_passed_through(monkeypatch):
    """excluded_source_files reaches the store unchanged."""
    store = _FakeVectorStore([_result("doc", "keep.pdf", 0.9, 0)])
    pipeline = _pipeline(store, monkeypatch)

    await pipeline.retrieve("q", excluded_source_files=["skip.pdf"])

    assert store.calls[0]["excluded"] == ["skip.pdf"]
