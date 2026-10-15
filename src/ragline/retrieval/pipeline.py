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

import asyncio
import re
from collections import Counter
from collections.abc import Callable

import structlog

from ragline.config import settings
from ragline.embeddings.base import BaseEmbedder
from ragline.retrieval.hybrid import BM25Index, reciprocal_rank_fusion
from ragline.retrieval.reranker import ApiReranker, Reranker
from ragline.tracing.collector import _current_trace, timed_step
from ragline.vectorstore.base import BaseVectorStore, SearchResult

log = structlog.get_logger()


class RetrievalPipeline:
    def __init__(self, vector_store: BaseVectorStore, embedder: BaseEmbedder):
        self._vector_store = vector_store
        self._embedder = embedder
        # Process-wide BM25 index; (re)built at startup and after ingestion.
        self._bm25 = BM25Index()
        # Optional observer for the evaluation harness: called once per
        # retrieve() with (fused candidates before rerank, final results after
        # rerank). None in production — nothing is copied or kept.
        self.capture: Callable[[list[SearchResult], list[SearchResult]], None] | None = None
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
        merged, results = await self._retrieve(query, top_k, allowed_document_ids, excluded_source_files)
        # Let an attached observer (evaluation only) see both candidate lists.
        if self.capture is not None:
            self.capture(merged, results)
        return results

    async def _retrieve(
        self,
        query: str,
        top_k: int | None,
        allowed_document_ids: list[str] | None,
        excluded_source_files: list[str] | None,
    ) -> tuple[list[SearchResult], list[SearchResult]]:
        """Hybrid + rerank for one query; returns (fused candidates, final results)."""
        top_k = top_k or settings.retrieval_top_k
        rerank_k = settings.rerank_top_k

        # An explicitly empty allow-list means "search nothing" (the chat
        # agent resolved document hints and found no matches).
        if allowed_document_ids is not None and not allowed_document_ids:
            return [], []

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

        # Cross-encoder rerank down to rerank_k plus a few spares (with the skip
        # heuristic), then drop duplicates and fragments and keep rerank_k.
        with timed_step("rerank"):
            ranked = await self._rerank(query, merged, rerank_k + settings.rerank_spare,
                                        dense_results=dense_results)
            results = tidy_results(ranked, rerank_k)

        log.info(
            "retrieval complete",
            query=query[:80],
            dense=len(dense_results),
            sparse=len(sparse_results),
            final=len(results),
            top_scores=[round(r.score, 4) for r in results[:5]],
            top_sources=[r.chunk.source_file for r in results[:5]],
        )
        return merged, results

    async def retrieve_multi(
        self,
        query: str,
        entity_queries: list[str],
        allowed_document_ids: list[str] | None = None,
        excluded_source_files: list[str] | None = None,
    ) -> list[SearchResult]:
        """Retrieve for a question about several products: one retrieval per product.

        A single query embedding lands on whichever product dominates the
        wording, so one product (or one manual) fills the context and the other
        side of a comparison never reaches the model. Here every per-product
        query gets its own retrieval + rerank and `entity_slots` reserved places
        in the final context; the main query fills the rest.
        """
        rerank_k = settings.rerank_top_k
        queries = entity_queries[: settings.max_entity_queries]
        # The main query and each product query run concurrently.
        # TODO(before intranet deploy): 1+N rerank calls hit one reranker GPU at
        # once; cap concurrent legs or batch the rerank before multi-user load
        # (ENTITY_SLOTS=0 switches per-entity retrieval off meanwhile).
        async def leg(q: str):
            """One retrieval, with its stage timings kept off the shared trace.

            The legs overlap in time, so summing each leg's embed/search/rerank
            onto the trace would overstate those stages; the whole fan-out is
            timed once as "multi_retrieve" instead. (Retrieval makes no LLM
            calls, so no token counts are lost; the task's context is a copy,
            so the caller's trace is untouched.)
            """
            _current_trace.set(None)
            return await self._retrieve(q, None, allowed_document_ids, excluded_source_files)

        with timed_step("multi_retrieve"):
            runs = await asyncio.gather(leg(query), *[leg(q) for q in queries])
        main, per_entity = runs[0][1], [r[1] for r in runs[1:]]
        final = merge_entity_results(main, per_entity, rerank_k, settings.entity_slots, settings.entity_doc_cap)
        log.info("multi-entity retrieval", queries=len(queries), final=len(final))
        # One observation for the evaluation harness: every fused pool, the final list.
        if self.capture is not None:
            pool: list[SearchResult] = []
            seen: set[tuple] = set()
            for fused, _ in runs:
                for r in fused:
                    if _key(r.chunk) not in seen:
                        seen.add(_key(r.chunk))
                        pool.append(r)
            self.capture(pool, final)
        return final

    async def expand_neighbours(self, results: list[SearchResult]) -> list[SearchResult]:
        """Insert a hit's neighbouring chunks when they continue it (a cut table or procedure).

        A table or numbered procedure split across chunks (or page breaks)
        leaves its rows or steps — or its header — in a chunk with no
        identifying words, which retrieval misses. When a hit ends on a table
        row or numbered step, or its next chunk starts with one, the next chunk
        is added right after it; when the hit starts with one, or its previous
        chunk ends with one, the previous chunk is added right before it. At
        most `neighbour_max_added` chunks are added, next chunks first.
        Citations stay page-exact: a neighbour is a real chunk with its own page.
        """
        if not settings.neighbour_expansion or not results:
            return results
        present = {_key(r.chunk) for r in results}
        # Positions already in the results are never fetched again.
        positions = {(r.chunk.document_id, r.chunk.chunk_index) for r in results}
        wanted = list(dict.fromkeys(
            (r.chunk.document_id, r.chunk.chunk_index + step) for step in (1, -1) for r in results
            if r.chunk.document_id and r.chunk.chunk_index + step >= 0
            and (r.chunk.document_id, r.chunk.chunk_index + step) not in positions))
        if not wanted:
            return results
        found = {(c.document_id, c.chunk_index): c
                 for c in await self._vector_store.get_chunks_by_position(wanted)}
        budget = settings.neighbour_max_added

        def pick(r: SearchResult, step: int):
            """The neighbour at `step` when it continues the hit and the budget allows."""
            nonlocal budget
            c = found.get((r.chunk.document_id, r.chunk.chunk_index + step))
            if c is None or budget <= 0 or _key(c) in present or (c.document_id, c.chunk_index) in positions:
                return None
            first, second = (r.chunk.text, c.text) if step == 1 else (c.text, r.chunk.text)
            if not continues(first, second):
                return None
            present.add(_key(c))
            positions.add((c.document_id, c.chunk_index))
            budget -= 1
            # At the parent's score, so reordering never separates them.
            return SearchResult(chunk=c, score=r.score)

        # Next chunks claim the budget first (they carry the cut-off rows/steps).
        after = [pick(r, 1) for r in results]
        before = [pick(r, -1) for r in results]
        out: list[SearchResult] = []
        for i, r in enumerate(results):
            out += [x for x in (before[i], r, after[i]) if x is not None]
        added = len(out) - len(results)
        if added:
            log.info("neighbour chunks added", added=added)
        return out

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


# --- result tidying, per-entity merge and neighbour rules (ragline-fixes-plan items 3-5) ---

# A markdown table row, or a numbered/lettered step at the start of a line.
_ROW = re.compile(r"^\s*\|.*\|\s*$")
_STEP = re.compile(r"^\s*(?:\(?\d{1,2}[.)]|[Ss][Tt][Ee][Pp]\s+\d+|[a-h][.)])\s+\S")


def _key(chunk) -> tuple:
    """Identity of a chunk for de-duplication across result lists."""
    return (chunk.chunk_id,) if chunk.chunk_id else (chunk.document_id, chunk.chunk_index)


def _has_row(text: str) -> bool:
    """True when any line of `text` is a markdown table row."""
    return any(_ROW.match(line) for line in text.splitlines())


def _norm(text: str) -> str:
    """Whitespace- and case-insensitive text, for exact-duplicate detection."""
    return re.sub(r"\s+", " ", text).strip().lower()


def tidy_results(ranked: list[SearchResult], keep: int) -> list[SearchResult]:
    """Drop exact-duplicate texts and fragments (shorter than min_context_chars), keep `keep`.

    The same passage often appears in two chapters or sibling manuals, and short
    footer chunks rank high because they name the product; both waste context
    slots. The spare candidates reranked beyond `keep` backfill what is dropped.
    """
    seen: set[str] = set()
    chosen: list[int] = []
    fragments: list[int] = []
    for i, r in enumerate(ranked):
        text = _norm(r.chunk.text)
        if text in seen:
            continue
        seen.add(text)
        # Short = fragment, unless it is the reranker's top pick or carries a
        # table row (a spec row such as "| DOP-107WV | 8.4 W |" is short but is the answer).
        if len(text) < settings.min_context_chars and i > 0 and not _has_row(r.chunk.text):
            fragments.append(i)
            continue
        chosen.append(i)
        if len(chosen) == keep:
            break
    # Too few full chunks: fragments come back (never duplicates), rank order kept.
    chosen = sorted(chosen + fragments[: max(0, keep - len(chosen))])
    return [ranked[i] for i in chosen]


def merge_entity_results(main: list[SearchResult], per_entity: list[list[SearchResult]],
                         keep: int, slots: int, doc_cap: int | None = None) -> list[SearchResult]:
    """Final context for a multi-product question: reserved slots per product, then the rest.

    Each product's list contributes its top `slots` (skipping chunks already
    taken); the main query's list fills the remaining places; any shortfall is
    filled round-robin from the product lists, then from the main list without
    the per-document cap. Order: the reserved slots first (product by
    product), then the fill.
    """
    doc_cap = keep if doc_cap is None else doc_cap
    taken: set[tuple] = set()
    out: list[SearchResult] = []

    def take(r: SearchResult) -> bool:
        k = _key(r.chunk)
        if k in taken or len(out) >= keep:
            return False
        taken.add(k)
        out.append(r)
        return True

    for results in per_entity:
        got = 0
        for r in results:
            if got >= slots:
                break
            got += take(r)
    # The main list fills the rest, at most doc_cap chunks per document, so
    # one manual cannot take every remaining place.
    per_doc = Counter(r.chunk.document_id for r in out)
    for r in main:
        if per_doc[r.chunk.document_id] < doc_cap and take(r):
            per_doc[r.chunk.document_id] += 1
    # Shortfall (few main results): continue through the product lists in turn.
    depth = 0
    while len(out) < keep and any(depth < len(rs) for rs in per_entity):
        for results in per_entity:
            if depth < len(results):
                take(results[depth])
        depth += 1
    # Still short: the main list again, without the cap.
    for r in main:
        take(r)
    return out


def continues(text: str, next_text: str) -> bool:
    """True when `next_text` carries on what `text` was in the middle of.

    A hit that ends on a table row or numbered step, or a next chunk that opens
    with one, is a table or procedure cut by the chunk boundary.
    """
    tail = [line for line in text.splitlines() if line.strip()][-1:] or [""]
    head = [line for line in next_text.splitlines() if line.strip()][:1] or [""]
    return bool(_ROW.match(tail[0]) or _STEP.match(tail[0]) or _ROW.match(head[0]) or _STEP.match(head[0]))
