"""Hybrid search primitives — in-memory BM25 index + Reciprocal Rank Fusion.

Ported verbatim (plus comments) from raggles. BM25 supplies the lexical half
of hybrid retrieval: exact part numbers and protocol names ("6ES7 214",
"PROFINET") that dense embeddings can blur. RRF merges the dense and sparse
ranked lists without needing their scores to be comparable.
"""

import re

import structlog
from rank_bm25 import BM25Okapi

from ragline.chunking.models import Chunk
from ragline.vectorstore.base import SearchResult

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# BM25 tokeniser — shared by the corpus and the query (plan item 1).
#
# ~27 % of this corpus is markdown tables whose cells fuse with pipes, `**`
# bold markers and `<br>` into unmatchable tokens (`|**attribute**|**2715-t7cd**<br>**2715-t7cd-b**|`);
# catalogue numbers in prose carry trailing punctuation (`2711p-t7c21d8s,`).
# A single whitespace split hides those tokens from BM25 and the user's
# "DOP-107WV" query never scores the table row that holds the answer.
#
# Rules applied, in order:
#   1. Lowercase the whole string.
#   2. Delete every HTML tag — `<br>`, `<sup>` and the rest — with `<[^>]*>`.
#   3. Replace markdown emphasis markers (`*`, `_`) and table pipes (`|`)
#      with a space so adjacent cells and bold runs fall apart cleanly.
#   4. Walk the string with `_TOKEN`: a run starting and ending with
#      alphanumerics, with any number of inner `-`, `.`, `/` characters.
#      This keeps catalogue/part numbers (`2711p-t7c21d8s`, `dop-107wv`,
#      `6200t-na`, `1756-l85e`, `v1.2`, `24vdc`, `8.4`) whole AND rejects
#      stray punctuation at either edge (`2711p-t7c21d8s,` → `2711p-t7c21d8s`).
#   5. For a kept whole token that contains `-`, `.` or `/`, also emit the
#      parts split on those characters (`2711p-t7c21d8s` → whole,
#      `2711p`, `t7c21d8s`; `v1.2` → whole, `v1`, `2`).
#   6. Drop empty tokens.
#
# Units: alphanumerics are kept as tokens, so `w`, `c`, `vdc`, `mhz` survive.
# Non-ASCII glyphs that are not alphanumeric (notably the degree sign in
# `°c`) are dropped by step 4, so `°c` reduces to `c` — documented, so a
# reader can see why the query `-20 °c` and the corpus text score together.
# ---------------------------------------------------------------------------

# HTML tag catch-all; a `<` with no closing `>` falls out of the regex and is
# left alone (not a tag — probably a stray less-than from a datasheet).
_HTML_TAG = re.compile(r"<[^>]*>")

# Characters replaced with a single space before token extraction: markdown
# emphasis markers that would otherwise fuse `**attribute**` into `attribute`
# with surrounding punctuation, and table pipes that glue cell contents.
_STRIP_TO_SPACE = str.maketrans({"*": " ", "_": " ", "|": " "})

# A token: an alphanumeric head, zero or more inner characters where the
# inner `-`, `.`, `/` are only kept when flanked by alphanumerics, and an
# alphanumeric tail. The second alternative handles the single-character
# case (`a`, `5`) that the first cannot match.
_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-./]*[a-z0-9]|[a-z0-9]")

# Separators split out when a whole identifier is also emitted as its parts.
_IDENT_SEP = re.compile(r"[-./]")


def tokenise(text: str) -> list[str]:
    """BM25 tokeniser used for both the corpus and the query — see rules above."""
    # Rule 1: lowercase so BM25 is case-insensitive without a second pass.
    lowered = text.lower()
    # Rule 2: strip HTML tags that corrupt table rows (`<br>` especially).
    without_tags = _HTML_TAG.sub(" ", lowered)
    # Rule 3: markdown emphasis and table pipes become whitespace boundaries.
    normalised = without_tags.translate(_STRIP_TO_SPACE)
    tokens: list[str] = []
    # Rule 4: extract clean, alphanumeric-anchored runs.
    for match in _TOKEN.finditer(normalised):
        token = match.group()
        # Rule 6: skip the empty token (the regex never matches it, kept for safety).
        if not token:
            continue
        tokens.append(token)
        # Rule 5: also emit sub-parts for hyphen/dot/slash-joined identifiers.
        if "-" in token or "." in token or "/" in token:
            for part in _IDENT_SEP.split(token):
                # The regex already rejects edge separators, so parts are non-empty,
                # but check anyway in case a future change loosens rule 4.
                if part:
                    tokens.append(part)
    return tokens


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
        # Shared tokeniser (see `tokenise` docstring): preserves catalogue
        # numbers in table cells so the query leg can match them.
        tokenized = [tokenise(chunk.text) for chunk in chunks]
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
        # Tokenise the query with the SAME function as the corpus (plan item 1):
        # a catalogue number in the query must land on the same bag of tokens
        # as the one indexed, parts and whole, or BM25 cannot match them.
        tokens = tokenise(query)
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
