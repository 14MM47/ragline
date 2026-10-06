"""extract_citations — parse [Source N] markers into a validated CitedResponse.

Ported byte-for-byte in behavior from raggles; this is the heart of the hard
citation chain. Responsibilities:

  * find every [Source N] / [Sources 1-3] / [Source 1, 3] marker (regex),
  * expand ranges and comma lists into individual source numbers,
  * DROP out-of-range numbers ("hallucinated source reference") — the LLM
    cannot cite a source that wasn't in the prompt,
  * split the answer into CitedSpans (text runs + attached citation ids),
  * deduplicate citations by (source_file, page_start) so the same file/page
    shows one badge no matter how many chunks it contributed,
  * heuristically realign a span's citation when token overlap shows the
    model systematically mis-numbered (e.g. tagging every claim [Source 1]).
"""

import re
from collections.abc import Iterable

import structlog

from ragline.chunking.models import Chunk
from ragline.citations.models import Citation, CitedResponse, CitedSpan

log = structlog.get_logger()

# Patterns matched: [Source 1], [Source 1, 3], [Sources 1-3], [Source 1][Source 2]
_CITATION_PATTERN = re.compile(r"\[Sources?\s+([\d,\s\-]+)\]")
# Guard against absurd ranges (e.g. "[Sources 1-9999999]"): any span wider than
# this is certainly malformed and must not be materialized into a giant list.
_MAX_RANGE_SPAN = 100
# Word tokens for the overlap heuristic.
_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Common words carrying no attribution signal.
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "over", "under",
    "your", "their", "there", "here", "have", "has", "had", "will", "would", "could",
    "should", "what", "when", "where", "which", "while", "who", "whom", "whose",
    "about", "than", "then", "also", "only", "just", "into", "onto", "were", "been",
}


def _parse_source_numbers(match_text: str) -> list[int]:
    """Parse '1, 3' or '1-3' into a list of ints (ranges expanded).

    Malformed fragments — dangling range bounds ("3-", "-1"), whitespace-only,
    or non-numeric junk — are skipped rather than raising: a stray marker from
    the LLM must never abort the whole citation extraction (and 500 the chat
    turn). Absurdly wide ranges are dropped so they can't blow up memory.
    """
    numbers: list[int] = []
    for part in match_text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            # "1-3" -> 1, 2, 3; skip if either bound is missing/non-numeric.
            start_s, end_s = (s.strip() for s in part.split("-", 1))
            if not start_s.isdigit() or not end_s.isdigit():
                continue
            start, end = int(start_s), int(end_s)
            if end < start or end - start > _MAX_RANGE_SPAN:
                continue
            numbers.extend(range(start, end + 1))
        elif part.isdigit():
            numbers.append(int(part))
    return numbers


def _tokenize(text: str) -> set[str]:
    """Meaningful lowercase tokens: >=3 chars, not stopwords."""
    toks = {
        t for t in _TOKEN_RE.findall(text.lower())
        if len(t) >= 3 and t not in _STOPWORDS
    }
    return toks


def _overlap_score(a: set[str], b: set[str]) -> float:
    """Token-overlap similarity normalized by geometric mean of set sizes."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    # Balanced overlap that prefers meaningful token intersection.
    return inter / ((len(a) * len(b)) ** 0.5)


def _ensure_citation_for_source(
    num: int,
    chunks: list[Chunk],
    citations_map: dict[int, Citation],
    dedup_map: dict[tuple[str, int | None], int],
    remap: dict[int, int],
) -> int:
    """Ensure a source number has a citation entry and return its citation_id.

    Dedup rule: two source numbers pointing at the same (document, page)
    collapse to ONE citation id — the first one seen — recorded in `remap`.
    Keyed on document_id, NOT source_file: source_file is only a basename, so
    two distinct documents sharing a filename (e.g. abb/manual.pdf and
    siemens/manual.pdf) must not be merged into one mis-attributed citation.
    """
    # Already collapsed onto an earlier citation?
    if num in remap:
        return remap[num]
    # Already has its own citation?
    if num in citations_map:
        return num

    # Source numbers are 1-based positions into the prompt's chunk list.
    chunk = chunks[num - 1]
    dedup_key = (chunk.document_id, chunk.page_start)
    existing_id = dedup_map.get(dedup_key)
    if existing_id is not None:
        # Same file+page as an earlier citation — collapse.
        remap[num] = existing_id
        return existing_id

    # New citation, built ENTIRELY from the chunk's carried identity.
    citations_map[num] = Citation(
        citation_id=num,
        source_file=chunk.source_file,
        page_number=chunk.page_start,
        section=chunk.section_header or None,
        quoted_text=chunk.text[:500],
        document_id=chunk.document_id,
    )
    dedup_map[dedup_key] = num
    return num


def _best_matching_source_num(
    span_text: str,
    chunk_tokens: list[set[str]],
) -> tuple[int | None, float]:
    """Which prompt source overlaps this span's wording best?"""
    span_tokens = _tokenize(span_text)
    # Too few meaningful tokens to judge.
    if len(span_tokens) < 3:
        return None, 0.0

    best_num: int | None = None
    best_score = 0.0
    for idx, toks in enumerate(chunk_tokens, start=1):
        score = _overlap_score(span_tokens, toks)
        if score > best_score:
            best_score = score
            best_num = idx
    return best_num, best_score


def _best_current_score(
    citation_ids: Iterable[int],
    span_text: str,
    chunk_tokens: list[set[str]],
) -> float:
    """How well do the span's CURRENT citations overlap its wording?"""
    span_tokens = _tokenize(span_text)
    if not span_tokens:
        return 0.0
    best = 0.0
    for cid in citation_ids:
        if 1 <= cid <= len(chunk_tokens):
            best = max(best, _overlap_score(span_tokens, chunk_tokens[cid - 1]))
    return best


def _realign_span_citations(
    spans: list[CitedSpan],
    chunks: list[Chunk],
    citations_map: dict[int, Citation],
    dedup_map: dict[tuple[str, int | None], int],
    remap: dict[int, int],
) -> None:
    """Heuristically realign citation IDs when model numbering is clearly off.

    This avoids obvious failure modes like every claim being tagged with one
    source ID. Thresholds (0.12 absolute, +0.08 margin) are raggles' tuned
    values: remap only when the alternative match is materially stronger.
    """
    # Pre-tokenize each chunk once (first 1500 chars carry the signal).
    chunk_tokens = [_tokenize(c.text[:1500]) for c in chunks]
    realigned = 0

    for span in spans:
        # Only spans that carry citations and enough text to judge.
        if not span.citation_ids:
            continue
        if len(span.text.strip()) < 20:
            continue

        best_num, best_score = _best_matching_source_num(span.text, chunk_tokens)
        if best_num is None:
            continue

        current_score = _best_current_score(span.citation_ids, span.text, chunk_tokens)
        # Remap only when best match is materially stronger.
        if best_score >= 0.12 and best_score >= current_score + 0.08:
            new_id = _ensure_citation_for_source(
                best_num, chunks, citations_map, dedup_map, remap
            )
            if span.citation_ids != [new_id]:
                span.citation_ids = [new_id]
                realigned += 1

    if realigned:
        log.info("realigned citations", spans=realigned)


def extract_citations(
    raw_text: str,
    chunks: list[Chunk],
    query: str,
    model_used: str,
) -> CitedResponse:
    """Parse LLM output with [Source N] markers into a CitedResponse.

    `chunks` MUST be the same list, in the same order, that
    format_sources_prompt numbered for the prompt.
    """
    num_sources = len(chunks)
    citations_map: dict[int, Citation] = {}
    dedup_map: dict[tuple[str, int | None], int] = {}  # (document_id, page) -> citation_id
    remap: dict[int, int] = {}  # source_num -> deduplicated citation_id
    spans: list[CitedSpan] = []

    # Walk the text, splitting at every citation marker.
    last_end = 0
    for match in _CITATION_PATTERN.finditer(raw_text):
        # Text between the previous marker and this one.
        before = raw_text[last_end : match.start()]
        if before.strip():
            spans.append(CitedSpan(text=before))

        source_nums = _parse_source_numbers(match.group(1))
        valid_nums = []

        for num in source_nums:
            if 1 <= num <= num_sources:
                # Valid reference — resolve through dedup.
                citation_id = _ensure_citation_for_source(
                    num, chunks, citations_map, dedup_map, remap
                )
                valid_nums.append(citation_id)
            else:
                # HALLUCINATION GUARD: the model cited a source that was
                # never in the prompt. Drop it — never invent a citation.
                log.warning("hallucinated source reference", source_num=num)

        if valid_nums:
            # Attach citations to the preceding text span, or (for adjacent
            # markers like [Source 1][Source 2]) an empty marker span.
            if spans and not spans[-1].citation_ids:
                spans[-1].citation_ids = valid_nums
            else:
                spans.append(CitedSpan(text="", citation_ids=valid_nums))

        last_end = match.end()

    # Trailing text after the final marker.
    remaining = raw_text[last_end:]
    if remaining.strip():
        spans.append(CitedSpan(text=remaining))

    # An answer with no markers at all is one uncited span.
    if not spans:
        spans = [CitedSpan(text=raw_text)]

    # Fix systematic mis-numbering before sources are finalized.
    _realign_span_citations(spans, chunks, citations_map, dedup_map, remap)

    # Emit ONLY citations some span still references. Realignment can move a
    # span off a citation that was its sole reference, orphaning it in
    # citations_map; such an orphan must not surface as a phantom source chip.
    referenced_ids = {cid for span in spans for cid in span.citation_ids}
    sources_used = sorted(
        (c for c in citations_map.values() if c.citation_id in referenced_ids),
        key=lambda c: c.citation_id,
    )

    return CitedResponse(
        spans=spans,
        sources_used=sources_used,
        query=query,
        model_used=model_used,
        raw_text=raw_text,
    )
