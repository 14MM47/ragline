"""ApiReranker slice batching — TEI caps one /rerank request at 32 texts.

A hybrid dense+sparse merge can reach 2*top_k (40) candidates, which TEI
rejects with 422 "batch size 40 > maximum allowed batch size 32". rerank()
must therefore score in <=32-text slices and re-offset each slice's local
`index` values before stitching the final ranking.
"""

import asyncio

from ragline.chunking.models import Chunk
from ragline.retrieval.reranker import ApiReranker
from ragline.vectorstore.base import SearchResult


def _result(idx: int) -> SearchResult:
    """One retrieval candidate whose text encodes its global position."""
    chunk = Chunk(
        text=f"chunk {idx}",
        source_file="test.pdf",
        document_id="doc-1",
        page_start=1,
        page_end=1,
        char_start=idx * 100,
        char_end=idx * 100 + 10,
        chunk_index=idx,
        chunk_id=f"doc-1-{idx}",
    )
    return SearchResult(chunk=chunk, score=0.5)


def test_40_candidates_scored_in_capped_slices(monkeypatch):
    """40 texts -> two slices (32 + 8), indices re-offset, order by score."""
    reranker = ApiReranker("http://example.invalid")
    batches: list[int] = []

    async def fake_score(query: str, texts: list[str]) -> list[dict]:
        # Record the slice size the server would have received.
        batches.append(len(texts))
        # Score each text by its GLOBAL position parsed from the text — but
        # return slice-LOCAL indices exactly as TEI does.
        return [
            {"index": i, "score": int(t.split()[1]) / 100.0}
            for i, t in enumerate(texts)
        ]

    monkeypatch.setattr(reranker, "_score", fake_score)

    results = [_result(i) for i in range(40)]
    ranked = asyncio.run(reranker.rerank("q", results, top_k=8))

    # Both slices under the TEI cap, covering all 40 texts.
    assert batches == [32, 8]
    # Highest global scores are 39..32 — all from the SECOND slice, which
    # only comes out right if the local indices were re-offset by the slice
    # start (an un-offset bug would return chunks 0..7 instead).
    assert [r.chunk.chunk_index for r in ranked] == [39, 38, 37, 36, 35, 34, 33, 32]


def test_under_cap_single_slice(monkeypatch):
    """A merge under the cap still goes out as one request."""
    reranker = ApiReranker("http://example.invalid")
    batches: list[int] = []

    async def fake_score(query: str, texts: list[str]) -> list[dict]:
        batches.append(len(texts))
        return [{"index": i, "score": 1.0 - i / 100.0} for i in range(len(texts))]

    monkeypatch.setattr(reranker, "_score", fake_score)

    ranked = asyncio.run(reranker.rerank("q", [_result(i) for i in range(20)], top_k=8))
    assert batches == [20]
    assert len(ranked) == 8


# --- Cohere-style /v1/rerank (vLLM pooling runner) --------------------------


def _mock_client(monkeypatch, handler):
    """Route every httpx.AsyncClient in reranker.py through a MockTransport."""
    import httpx

    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        # Keep the caller's kwargs (timeout) but swap in the fake transport.
        return real(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("ragline.retrieval.reranker.httpx.AsyncClient", factory)


def test_cohere_format_request_and_response_shape(monkeypatch):
    """cohere: POST {base}/v1/rerank with `documents`; parse results[].relevance_score."""
    import json

    import httpx

    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"url": str(request.url), "body": body,
                     "auth": request.headers.get("authorization")})
        # vLLM returns results sorted by score, NOT input order — score by the
        # global position encoded in the text, descending.
        results = sorted(
            ({"index": i, "relevance_score": int(t.split()[1]) / 100.0,
              "document": {"text": t}} for i, t in enumerate(body["documents"])),
            key=lambda r: r["relevance_score"], reverse=True,
        )
        return httpx.Response(200, json={"id": "x", "model": "m", "results": results})

    _mock_client(monkeypatch, handler)
    reranker = ApiReranker("http://pod.invalid/", api_key="tok", api_format="cohere")
    ranked = asyncio.run(reranker.rerank("q", [_result(i) for i in range(40)], top_k=8))

    # One request (no TEI 32-cap slicing), right path, Cohere body, bearer sent.
    assert len(seen) == 1
    assert seen[0]["url"] == "http://pod.invalid/v1/rerank"
    assert seen[0]["body"]["query"] == "q"
    assert len(seen[0]["body"]["documents"]) == 40
    assert "texts" not in seen[0]["body"]
    assert seen[0]["auth"] == "Bearer tok"
    # Index mapping survives the server's score-sorted order.
    assert [r.chunk.chunk_index for r in ranked] == [39, 38, 37, 36, 35, 34, 33, 32]
    assert ranked[0].score == 0.39


def test_tei_format_request_shape_unchanged(monkeypatch):
    """tei (default): POST {base}/rerank with `texts`; [{index, score}] parsed as-is."""
    import json

    import httpx

    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"url": str(request.url), "body": body})
        return httpx.Response(200, json=[{"index": i, "score": 1.0 - i / 100.0}
                                         for i in range(len(body["texts"]))])

    _mock_client(monkeypatch, handler)
    ranked = asyncio.run(ApiReranker("http://pod.invalid").rerank(
        "q", [_result(i) for i in range(3)], top_k=2))

    assert seen[0]["url"] == "http://pod.invalid/rerank"
    assert seen[0]["body"] == {"query": "q", "texts": ["chunk 0", "chunk 1", "chunk 2"],
                               "raw_scores": False}
    assert [r.chunk.chunk_index for r in ranked] == [0, 1]


def test_unknown_format_rejected_at_construction():
    """A typo in RERANKER_API_FORMAT fails at startup, not on the first query."""
    import pytest

    with pytest.raises(ValueError, match="RERANKER_API_FORMAT"):
        ApiReranker("http://pod.invalid", api_format="jina")


def test_out_of_range_index_dropped_not_crash(monkeypatch):
    """A server returning an index outside the input degrades, never IndexErrors."""
    reranker = ApiReranker("http://example.invalid")

    async def fake_score(query: str, texts: list[str]) -> list[dict]:
        # One valid item plus two bogus indices (past the end, and negative).
        return [{"index": 0, "score": 0.9}, {"index": 99, "score": 0.8}, {"index": -1, "score": 0.7}]

    monkeypatch.setattr(reranker, "_score", fake_score)
    ranked = asyncio.run(reranker.rerank("q", [_result(0), _result(1)], top_k=8))
    # Only the in-range result survives; the query still succeeds.
    assert [r.chunk.chunk_index for r in ranked] == [0]


def test_cohere_without_key_warns_at_startup(monkeypatch):
    """cohere + empty key logs a startup warning (vLLM would 401 every call)."""
    warnings: list[str] = []
    # Capture structlog warnings from the reranker module's logger.
    monkeypatch.setattr("ragline.retrieval.reranker.log.warning",
                        lambda msg, **kw: warnings.append(msg))
    ApiReranker("http://pod.invalid", api_key="", api_format="cohere")
    ApiReranker("http://pod.invalid", api_key="tok", api_format="cohere")
    ApiReranker("http://pod.invalid", api_key="", api_format="tei")
    # Exactly one warning: only the keyless cohere construction.
    assert len(warnings) == 1 and "RERANKER_API_KEY" in warnings[0]
