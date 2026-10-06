"""RetrievalPipeline — the single retrieval path every query takes.

Ported from raggles with every playground branch removed (CRAG, semantic
cache, adaptive depth, HyDE execution, parent-child, ColPali, step-back).
The surviving flow — raggles' proven core:

    embed query -> dense search (Qdrant, server-side filters)
                +  sparse search (in-memory BM25)
    -> Reciprocal Rank Fusion -> cross-encoder rerank (with score-gap skip)
    -> top rerank_k results

Scoping filters (allowed_document_ids / excluded_source_files) come from the
chat pre-pass and are applied identically on both search legs.
"""

import structlog

from ragline.config import settings
from ragline.embeddings.base import BaseEmbedder
from ragline.retrieval.hybrid import BM25Index, reciprocal_rank_fusion
from ragline.retrieval.reranker import ApiReranker, Reranker
from ragline.tracing.collector import timed_step
from ragline.vectorstore.base import BaseVectorStore, SearchResult

log = structlog.get_logger()


class RetrievalPipeline:
    def __init__(self, vector_store: BaseVectorStore, embedder: BaseEmbedder):
        self._vector_store = vector_store
        self._embedder = embedder
        # Process-wide BM25 index; (re)built at startup and after ingestion.
        self._bm25 = BM25Index()
        # Reranker: local CPU cross-encoder, a remote TEI /rerank endpoint, or
        # none. All three leave _reranker as None-or-async-rerank(); failures
        # degrade to fusion order rather than breaking retrieval.
        self._reranker: Reranker | ApiReranker | None = None
        if settings.reranker_provider == "local":
            try:
                self._reranker = Reranker(settings.reranker_model)
            except Exception:
                # Missing model/download failure degrades to fusion order.
                log.warning("failed to load reranker, falling back to raw scores")
        elif settings.reranker_provider == "api":
            if settings.reranker_base_url:
                self._reranker = ApiReranker(
                    settings.reranker_base_url,
                    settings.reranker_api_key,
                    api_format=settings.reranker_api_format,
                )
                log.info("using api reranker", url=settings.reranker_base_url)
            else:
                # Misconfiguration shouldn't crash startup — warn and skip.
                log.warning("reranker_provider=api but RERANKER_BASE_URL is unset; reranking disabled")

    async def rebuild_bm25_index(self) -> None:
        """Rebuild BM25 from every chunk payload in the vector store."""
        chunks = await self._vector_store.get_all_chunks()
        self._bm25.build(chunks)

    async def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        allowed_document_ids: list[str] | None = None,
        excluded_source_files: list[str] | None = None,
    ) -> list[SearchResult]:
        """Run the full hybrid + rerank flow for one query."""
        top_k = top_k or settings.retrieval_top_k
        rerank_k = settings.rerank_top_k

        # An explicitly empty allow-list means "search nothing" (the chat
        # agent resolved document hints and found no matches).
        if allowed_document_ids is not None and not allowed_document_ids:
            return []

        # One dense query embedding via the configured endpoint.
        with timed_step("embed_query"):
            query_embedding = await self._embedder.embed_query(query)

        # Dense leg: Qdrant similarity with server-side pre-filtering.
        with timed_step("vector_search"):
            dense_results = await self._vector_store.search_filtered(
                query_embedding,
                top_k=top_k,
                allowed_document_ids=allowed_document_ids,
                excluded_source_files=excluded_source_files,
            )
        with timed_step("sparse_merge"):
            # Sparse leg: BM25 with identical filters.
            sparse_results = self._bm25.search(
                query,
                top_k=top_k,
                allowed_document_ids=allowed_document_ids,
                excluded_source_files=excluded_source_files,
            )

            # Fuse both rankings when the sparse leg produced anything.
            if sparse_results:
                merged = reciprocal_rank_fusion([dense_results, sparse_results])
            else:
                merged = dense_results

        # Cross-encoder rerank down to rerank_k (with the skip heuristic).
        with timed_step("rerank"):
            results = await self._rerank(query, merged, rerank_k, dense_results=dense_results)

        log.info(
            "retrieval complete",
            query=query[:80],
            dense=len(dense_results),
            sparse=len(sparse_results),
            final=len(results),
            top_scores=[round(r.score, 4) for r in results[:5]],
            top_sources=[r.chunk.source_file for r in results[:5]],
        )
        return results

    async def _rerank(
        self,
        query: str,
        merged: list[SearchResult],
        rerank_k: int,
        dense_results: list[SearchResult] | None = None,
    ) -> list[SearchResult]:
        """Apply the cross-encoder unless disabled, unnecessary, or skippable."""
        if self._reranker and len(merged) > rerank_k:
            # Clear dense winner? Save the cross-encoder pass entirely.
            if self._should_skip_rerank(merged, dense_results):
                return merged[:rerank_k]
            return await self._reranker.rerank(query, merged, top_k=rerank_k)
        # No reranker (or already few enough results): keep fusion order.
        return merged[:rerank_k]

    @staticmethod
    def _should_skip_rerank(
        merged: list[SearchResult],
        dense_results: list[SearchResult] | None,
    ) -> bool:
        """Skip the cross-encoder when the top result is clearly dominant.

        Dominance is judged on the dense cosine scores (the thresholds are
        calibrated for that scale — RRF-merged scores max out around 2/61 and
        would never trigger), and only acted on when fusion kept the dominant
        chunk at rank 1, since what a skip returns is the merged list.
        """
        # Judge on dense scores when available; merged otherwise.
        source = dense_results if dense_results else merged
        scores = [r.score for r in source]
        if len(scores) < 2:
            return False
        # Gap between the top score and the mean of the rest.
        gap = scores[0] - (sum(scores[1:]) / len(scores[1:]))
        if gap <= settings.reranker_skip_score_gap:
            return False
        # The winner must also be strong in absolute terms.
        if scores[0] <= settings.reranker_skip_min_top_score:
            return False
        # Only safe when fusion kept that same chunk at rank 1 (a skip
        # returns the MERGED order, not the dense order).
        if not merged or not _same_chunk(source[0].chunk, merged[0].chunk):
            return False
        log.info(
            "reranker skipped (score gap)",
            gap=round(gap, 4),
            top_score=round(scores[0], 4),
        )
        return True


def _same_chunk(a, b) -> bool:
    """Chunk identity: by stable id when both have one, else by coordinates."""
    if a.chunk_id and b.chunk_id:
        return a.chunk_id == b.chunk_id
    return (a.document_id, a.char_start, a.chunk_index) == (
        b.document_id,
        b.char_start,
        b.chunk_index,
    )
