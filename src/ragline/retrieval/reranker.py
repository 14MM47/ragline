"""Reranker — cross-encoder scoring of (query, chunk) pairs.

Two interchangeable providers, both with the same async rerank() interface:

  * Reranker (RERANKER_PROVIDER=local): the cross-encoder (default
    BAAI/bge-reranker-v2-m3) runs in-process on CPU via sentence-transformers.
    Fully air-gapped, but CPU inference is slow (seconds/query).
  * ApiReranker (RERANKER_PROVIDER=api): the reranker runs on a GPU pod
    behind either a TEI (text-embeddings-inference) /rerank endpoint or a
    Cohere-style /v1/rerank endpoint (vLLM pooling runner), chosen by
    RERANKER_API_FORMAT. This is the ONE query-side component the
    OpenAI-compatible endpoint can't serve (the OpenAI API has no rerank op),
    so it gets its own service.

RERANKER_PROVIDER=none disables reranking (fusion order is used as-is).
"""

import asyncio

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from ragline.vectorstore.base import SearchResult

log = structlog.get_logger()


class Reranker:
    def __init__(self, model_name: str):
        # Lazy import so an api/none deploy needn't install sentence-transformers.
        from sentence_transformers import CrossEncoder

        # Downloads the model on first construction; cached in ~/.cache after.
        self._model = CrossEncoder(model_name)
        log.info("loaded reranker model", model=model_name)

    async def rerank(self, query: str, results: list[SearchResult], top_k: int = 8) -> list[SearchResult]:
        """Score every (query, chunk) pair and return the best top_k."""
        if not results:
            return []

        # Cross-encoders read query and passage TOGETHER — far more accurate
        # than comparing two independent embeddings, and far slower; hence
        # rerank only the ~20 hybrid candidates, not the whole corpus.
        pairs = [(query, r.chunk.text) for r in results]
        # predict() is CPU-bound transformer inference (seconds). Run it in a
        # worker thread so it never blocks the single event loop — otherwise
        # every concurrent request (other chats, batch polling, /health)
        # stalls for the whole rerank.
        scores = await asyncio.to_thread(self._model.predict, pairs)

        # Sort candidates by cross-encoder score, keep the best top_k.
        scored = list(zip(results, scores))
        scored.sort(key=lambda x: x[1], reverse=True)

        reranked = [
            SearchResult(chunk=r.chunk, score=float(s)) for r, s in scored[:top_k]
        ]
        log.debug("reranked results", input_count=len(results), output_count=len(reranked))
        return reranked


class ApiReranker:
    """Reranker backed by a remote rerank endpoint on a GPU pod.

    Same async interface as Reranker, so the pipeline treats them identically.
    Offloads the model to the pod — no ~2GB local model, no CPU-bound
    inference blocking anything. Point RERANKER_BASE_URL at the server root.

    api_format picks the wire format:
      * "tei"    — TEI native POST /rerank {query, texts} -> [{index, score}]
                   (e.g. bge-reranker-v2-m3 on TEI).
      * "cohere" — POST /v1/rerank {query, documents} ->
                   {results: [{index, relevance_score}]}, as served by vLLM
                   (e.g. Qwen3-Reranker-4B) and Cohere/Jina-compatible APIs.
    Both are normalised to [{index, score}] before ranking.
    """

    _FORMATS = ("tei", "cohere")

    # TEI's default --max-client-batch-size is 32: one /rerank request may
    # carry at most 32 texts or the server answers 422. A hybrid merge of
    # dense + sparse top-k can reach 2*top_k texts (40 at the default 20),
    # so rerank() scores in slices of this size and stitches the results.
    _MAX_CLIENT_BATCH = 32

    def __init__(self, base_url: str, api_key: str = "", api_format: str = "tei"):
        # Fail at startup on a typo rather than on the first query.
        if api_format not in self._FORMATS:
            raise ValueError(f"RERANKER_API_FORMAT must be one of {self._FORMATS}, got {api_format!r}")
        self._format = api_format
        # TEI exposes POST {base}/rerank; vLLM/Cohere style is POST {base}/v1/rerank
        # (the /v1 path is also the one vLLM's --api-key bearer check covers).
        path = "/rerank" if api_format == "tei" else "/v1/rerank"
        self._url = base_url.rstrip("/") + path
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # A vLLM reranker always requires the bearer; without one every query
        # would 401. Say so at startup instead of on the first rerank.
        if api_format == "cohere" and not api_key:
            log.warning("RERANKER_API_FORMAT=cohere with no RERANKER_API_KEY; requests will likely 401")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def _score(self, query: str, texts: list[str]) -> list[dict]:
        """POST the (query, texts) to the endpoint; returns [{index, score}, ...]."""
        # Request body in the configured wire format.
        if self._format == "tei":
            body = {"query": query, "texts": texts, "raw_scores": False}
        else:
            # top_n = all: rerank() does its own top_k cut after merging.
            body = {"query": query, "documents": texts, "top_n": len(texts)}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self._url, json=body, headers=self._headers)
            resp.raise_for_status()
            data = resp.json()
        # TEI already answers [{index, score}]; normalise the Cohere shape to it.
        if self._format == "tei":
            return data
        return [
            {"index": item["index"], "score": item["relevance_score"]}
            for item in data["results"]
        ]

    async def rerank(self, query: str, results: list[SearchResult], top_k: int = 8) -> list[SearchResult]:
        """Score (query, chunk) pairs on the pod and return the best top_k."""
        if not results:
            return []

        texts = [r.chunk.text for r in results]

        # Score in server-cap-sized slices; each response's `index` is local
        # to its slice, so re-offset by the slice start before merging. Only
        # TEI has the 32-text cap — the Cohere-style endpoint takes all at once.
        slice_size = self._MAX_CLIENT_BATCH if self._format == "tei" else max(len(texts), 1)
        scored: list[dict] = []
        for start in range(0, len(texts), slice_size):
            part = await self._score(query, texts[start : start + slice_size])
            scored.extend(
                {"index": item["index"] + start, "score": item["score"]} for item in part
            )

        # Items carry the input `index` and a `score` (normalised); map each
        # back to its SearchResult (defensively re-sort — never assume order).
        # Drop any index outside the input: a misbehaving server must degrade
        # the ranking, not crash the query with an IndexError.
        in_range = [item for item in scored if 0 <= item["index"] < len(results)]
        if len(in_range) != len(scored):
            log.warning("reranker returned out-of-range indices", dropped=len(scored) - len(in_range))
        ranked = [
            SearchResult(chunk=results[item["index"]].chunk, score=float(item["score"]))
            for item in in_range
        ]
        ranked.sort(key=lambda r: r.score, reverse=True)
        log.debug("reranked results (api)", input_count=len(results), output_count=min(top_k, len(ranked)))
        return ranked[:top_k]
