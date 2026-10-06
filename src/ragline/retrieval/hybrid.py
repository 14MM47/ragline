"""Hybrid search primitives — in-memory BM25 index + Reciprocal Rank Fusion.

Ported verbatim (plus comments) from raggles. BM25 supplies the lexical half
of hybrid retrieval: exact part numbers and protocol names ("6ES7 214",
"PROFINET") that dense embeddings can blur. RRF merges the dense and sparse
ranked lists without needing their scores to be comparable.
"""

import structlog
from rank_bm25 import BM25Okapi

from ragline.chunking.models import Chunk
from ragline.vectorstore.base import SearchResult

log = structlog.get_logger()


def _expanded_excluded_casefold(excluded_source_files: list[str]) -> set[str]:
    """Casefolded exclusion names PLUS their bare basenames.

    Mirrors the dense leg (QdrantVectorStore._excluded_casefold) exactly so both
    retrieval legs filter exclusions identically — the pre-pass may name either
    the full stored path or just the basename, in any case.
    """
    expanded: set[str] = set()
    for source_file in excluded_source_files:
        expanded.add(source_file.casefold())
        basename = source_file.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if basename:
            expanded.add(basename.casefold())
    return expanded


class BM25Index:
    """In-memory BM25 index over chunk texts.

    Rebuilt from the vector store's payloads at startup and after every
    ingestion batch/delete (see RetrievalPipeline.rebuild_bm25_index).
    """

    def __init__(self):
        # Chunks in index order — BM25 scores map back to these by position.
        self._chunks: list[Chunk] = []
        self._index: BM25Okapi | None = None

    def build(self, chunks: list[Chunk]) -> None:
        """(Re)build the index over the given chunks."""
        self._chunks = chunks
        if not chunks:
            # Empty corpus -> no index; search() returns [].
            self._index = None
            log.info("built bm25 index", num_chunks=0)
            return
        # Simple whitespace tokenization, lowercased — adequate for technical
        # text where part numbers matter more than stemming.
        tokenized = [chunk.text.lower().split() for chunk in chunks]
        self._index = BM25Okapi(tokenized)
        log.info("built bm25 index", num_chunks=len(chunks))

    def search(
        self,
        query: str,
        top_k: int = 20,
        allowed_document_ids: list[str] | None = None,
        excluded_source_files: list[str] | None = None,
    ) -> list[SearchResult]:
        """Lexical search with the same scoping filters as the dense side."""
        if self._index is None or not self._chunks:
            return []
        # Tokenize the query the same way as the corpus.
        tokens = query.lower().split()
        scores = self._index.get_scores(tokens)
        # Precompute filter sets (None = unrestricted).
        allowed_set = set(allowed_document_ids) if allowed_document_ids is not None else None
        excluded_set = (
            _expanded_excluded_casefold(excluded_source_files) if excluded_source_files else None
        )

        # Collect indices that pass filters and actually matched something.
        candidate_indices: list[int] = []
        for i, chunk in enumerate(self._chunks):
            if allowed_set is not None and chunk.document_id not in allowed_set:
                continue
            if excluded_set and chunk.source_file.casefold() in excluded_set:
                continue
            # Zero score = no query term present.
            if scores[i] <= 0:
                continue
            candidate_indices.append(i)

        # Best top_k by BM25 score.
        top_indices = sorted(candidate_indices, key=lambda i: scores[i], reverse=True)[:top_k]
        return [
            SearchResult(chunk=self._chunks[i], score=float(scores[i]))
            for i in top_indices
        ]


def reciprocal_rank_fusion(
    result_lists: list[list[SearchResult]],
    k: int = 60,
    weights: list[float] | None = None,
) -> list[SearchResult]:
    """Merge multiple ranked lists using Reciprocal Rank Fusion.

    Each item contributes weight/(k + rank + 1) per list it appears in; items
    ranked highly in BOTH lists rise to the top. RRF scores by rank, not by
    the input scores, so dense cosine and BM25 scores never need calibrating
    against each other. k=60 is the standard damping constant.
    """
    # Default: all lists count equally.
    if weights is None:
        weights = [1.0] * len(result_lists)
    scores: dict[int, float] = {}
    chunk_map: dict[int, SearchResult] = {}

    for weight, results in zip(weights, result_lists, strict=True):
        for rank, result in enumerate(results):
            # Chunk identity: same document + same offsets = same chunk,
            # regardless of which list it came from.
            key = hash((result.chunk.document_id, result.chunk.char_start, result.chunk.chunk_index))
            if key not in chunk_map:
                chunk_map[key] = result
                scores[key] = 0.0
            # Higher rank (smaller index) contributes more.
            scores[key] += weight / (k + rank + 1)

    # Emit in fused-score order.
    sorted_keys = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [
        SearchResult(chunk=chunk_map[key].chunk, score=scores[key]) for key in sorted_keys
    ]
