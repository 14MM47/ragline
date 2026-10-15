"""Structural chunking — token-budgeted chunks at sentence and table-row boundaries.

Ported from raggles (its default and best-validated strategy; the semantic /
proposition alternatives were playground experiments and are not ported).

Guarantees the citation machinery relies on:
  * a chunk NEVER spans pages (page_start == page_end always), so a citation's
    page number is exact;
  * chunks respect the token budget except single sentences or table rows that
    alone exceed it (kept whole as their own chunk rather than split);
  * consecutive prose chunks overlap by ~overlap_fraction of the budget so
    answers that straddle a boundary are still retrievable.

Tables (added 2026-10 for the evaluation index, see docs/eval/phase0-index-plan.md):
  * a markdown table row is atomic — a chunk boundary never falls inside a row;
  * a table longer than the budget is cut only between rows, and every
    continuation chunk starts with a copy of the table's header rows, so a row
    is never separated from the column names (catalogue numbers, units) that
    give it meaning;
  * no sentence overlap is carried into or out of a table chunk — the repeated
    header is that chunk's overlap.

Tiny chunks: a chunk under the minimum (default 48 tokens) is folded into its
neighbour on the same page, so stray fragments (a contact line, a document
code) cannot become stand-alone retrieval decoys.
"""

import re
from dataclasses import dataclass, replace

import structlog
import tiktoken

from ragline.chunking.models import Chunk
from ragline.config import settings
from ragline.parsing.models import ParsedDocument

log = structlog.get_logger()

# A markdown table row as the parsers emit it: "| a | b |" alone on its line.
_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
# A markdown header separator row: pipes, dashes, colons and spaces only.
_SEP_RE = re.compile(r"^\s*\|[\s:|-]*-{3,}[\s:|-]*\|\s*$")
# The separator must sit within this many rows of the table top to count as a
# header separator (pymupdf4llm sometimes emits a spanning title row first).
_SEP_MAX_INDEX = 2
# Bold-only rows directly below the separator also belong to the header (the
# PanelView "Attribute | 2715-T7CD | …" row sits under a spanning group row);
# at most this many are taken.
_MAX_EXTRA_HEADER_ROWS = 2


@dataclass
class _Unit:
    """One indivisible piece of page text: a prose sentence or a table row."""

    # The text exactly as it goes into the chunk.
    text: str
    # Character offset of the text within the page's text.
    start: int
    # Token count under the chunking encoding.
    tokens: int
    # Table block number on this page; None for prose.
    table: int | None = None
    # True for the table's header rows (column names).
    is_header: bool = False
    # For a header row copied into a continuation chunk: the original unit.
    origin: "_Unit | None" = None

    @property
    def key(self) -> int:
        """Identity of the underlying text (copies share their original's key)."""
        return id(self.origin) if self.origin is not None else id(self)


def _count_tokens(text: str, encoding: tiktoken.Encoding) -> int:
    """Token count under the given encoding (gpt-4o's cl100k-family)."""
    return len(encoding.encode(text))


def _make_chunk(
    text: str,
    source_file: str,
    document_id: str,
    page_number: int,
    char_start: int,
    section_header: str,
    chunk_index: int,
    char_end: int | None = None,
) -> Chunk:
    """Build one page-anchored Chunk.

    char_end defaults to char_start + len(text); callers that prepend a
    repeated table header pass the real end offset instead.
    page_start == page_end always — a chunk never spans pages, so the citation
    page number stays exact.
    """
    return Chunk(
        text=text,
        source_file=source_file,
        document_id=document_id,
        page_start=page_number,
        page_end=page_number,
        char_start=char_start,
        char_end=char_end if char_end is not None else char_start + len(text),
        section_header=section_header,
        chunk_index=chunk_index,
    )


def _split_at_sentence_boundaries(text: str) -> list[str]:
    """Split text into sentences, keeping the terminating punctuation attached."""
    # Split after ., ! or ? followed by whitespace; simple but robust across
    # the markdown-ish text our parsers produce.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s for s in sentences if s.strip()]


def _is_bold_row(row: str) -> bool:
    """True when every non-empty cell of a markdown row is bold (**…**)."""
    # Drop the outer pipes, then split into cells.
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    # Only cells that hold something are judged.
    filled = [c for c in cells if c]
    # An all-empty row is not a header; otherwise every cell must open bold.
    return bool(filled) and all(c.startswith("**") for c in filled)


def _header_row_count(rows: list[str]) -> int:
    """How many leading rows of a table are its header (0 = no header)."""
    # Find the separator among the first few rows.
    sep = next((i for i, r in enumerate(rows[: _SEP_MAX_INDEX + 1]) if _SEP_RE.match(r)), None)
    # No separator near the top: the table has no recognisable header.
    if sep is None:
        return 0
    # Everything up to and including the separator is header.
    count = sep + 1
    # Plus up to _MAX_EXTRA_HEADER_ROWS all-bold rows straight after it.
    while (
        count < len(rows)
        and count - (sep + 1) < _MAX_EXTRA_HEADER_ROWS
        and _is_bold_row(rows[count])
    ):
        count += 1
    # A "header" that is the whole table is no header at all (nothing to repeat it for).
    return count if count < len(rows) else 0


def _page_units(text: str, enc: tiktoken.Encoding) -> list[_Unit]:
    """Cut one page's text into ordered prose-sentence and table-row units."""
    # Group consecutive lines into blocks of the same kind (prose or row),
    # tracking each line's offset in the page text.
    blocks: list[tuple[str, list[tuple[int, str]]]] = []
    pos = 0
    for line in text.splitlines(keepends=True):
        # A table row line, or anything else (prose, blank lines, headings).
        kind = "row" if _ROW_RE.match(line) else "prose"
        # Extend the current block when the kind continues, else open a new one.
        if blocks and blocks[-1][0] == kind:
            blocks[-1][1].append((pos, line))
        else:
            blocks.append((kind, [(pos, line)]))
        pos += len(line)

    units: list[_Unit] = []
    table_no = 0
    for kind, lines in blocks:
        if kind == "prose":
            # The prose block as one string, starting at its first line's offset.
            seg_start = lines[0][0]
            segment = "".join(line for _, line in lines)
            cursor = 0
            for sentence in _split_at_sentence_boundaries(segment):
                # Sentences are stripped (as the page text used to be); locate
                # each one after the previous so duplicates map correctly.
                s = sentence.strip()
                at = segment.find(s, cursor)
                cursor = at + len(s)
                units.append(_Unit(s, seg_start + at, _count_tokens(s, enc)))
        else:
            # A table block: header rows first, then data rows, each atomic.
            rows = [line.strip() for _, line in lines]
            n_header = _header_row_count(rows)
            for i, (offset, line) in enumerate(lines):
                # Offset of the row's first non-blank character.
                start = offset + (len(line) - len(line.lstrip()))
                units.append(_Unit(rows[i], start, _count_tokens(rows[i], enc),
                                   table=table_no, is_header=i < n_header))
            table_no += 1
    return units


def _join(units: list[_Unit]) -> str:
    """Join units into chunk text: sentences by spaces, rows by newlines."""
    out = units[0].text
    for prev, cur in zip(units, units[1:]):
        if prev.table is None and cur.table is None:
            # Prose to prose: the sentence splitter ate a run of whitespace.
            sep = " "
        elif prev.table is not None and prev.table == cur.table:
            # Row to row of the same table: keep it a markdown table.
            sep = "\n"
        else:
            # Prose to table, table to prose, or table to another table.
            sep = "\n\n"
        out += sep + cur.text
    return out


def _tokens(units: list[_Unit]) -> int:
    """Token total of a list of units (separators are not counted, as before)."""
    return sum(u.tokens for u in units)


def _merge_tiny(page_chunks: list[list[_Unit]], min_tokens: int) -> list[list[_Unit]]:
    """Fold chunks under min_tokens into a neighbour on the same page."""
    merged: list[list[_Unit]] = []
    for units in page_chunks:
        if merged and _tokens(units) < min_tokens:
            # A tiny chunk after a sibling: append it, minus any units the
            # sibling already holds (overlap sentences, repeated header rows).
            have = {u.key for u in merged[-1]}
            merged[-1] = merged[-1] + [u for u in units if u.key not in have]
        else:
            merged.append(units)
    if len(merged) > 1 and _tokens(merged[0]) < min_tokens:
        # A tiny first chunk: prepend it to the next one, which may carry it
        # as overlap or repeat its header rows already.
        head = merged.pop(0)
        have = {u.key for u in head}
        merged[0] = head + [u for u in merged[0] if u.key not in have]
    # A page that yields a single tiny chunk keeps it: there is nothing to merge with.
    return merged


def _page_chunks(units: list[_Unit], max_tokens: int, overlap_tokens: int) -> list[list[_Unit]]:
    """Pack one page's units into chunks under the budget."""
    # Header rows per table, for repeating at the top of continuation chunks.
    headers: dict[int, list[_Unit]] = {}
    for u in units:
        if u.is_header:
            headers.setdefault(u.table, []).append(u)

    def header_copy(u: _Unit) -> list[_Unit]:
        """Copies of u's table header to open a continuation chunk (or none)."""
        hdr = headers.get(u.table) if u.table is not None and not u.is_header else None
        # Only repeated while it costs at most half the budget, so a huge
        # header cannot crowd every continuation chunk out.
        if not hdr or _tokens(hdr) > max_tokens // 2:
            return []
        return [replace(h, origin=h) for h in hdr]

    def overlap(prev: list[_Unit]) -> list[_Unit]:
        """Trailing prose sentences of prev, up to the overlap budget."""
        seed: list[_Unit] = []
        tok = 0
        for s in reversed(prev):
            # Never carry table rows forward as overlap, and stop at the budget.
            if s.table is not None or tok + s.tokens > overlap_tokens:
                break
            seed.insert(0, s)
            tok += s.tokens
        return seed

    def detach_header(cur: list[_Unit], u: _Unit) -> tuple[list[_Unit], list[_Unit]]:
        """Split off cur's trailing copy-free header of u's table, if nothing sits under it.

        Returns (what stays, the header rows to move forward). Moving the header
        avoids closing a chunk on column names with no row beneath them.
        """
        hdr = headers.get(u.table) if u.table is not None and not u.is_header else None
        # Also when the header is ALL of cur: leaving it would emit a data-less
        # header-only chunk (a retrieval decoy); callers skip an emptied cur.
        if hdr and len(cur) >= len(hdr) and [x.key for x in cur[-len(hdr):]] == [h.key for h in hdr]:
            return cur[: -len(hdr)], cur[-len(hdr):]
        return cur, []

    # Accumulators: the finished chunks, the chunk under construction and its size.
    chunks: list[list[_Unit]] = []
    current: list[_Unit] = []
    current_tokens = 0

    for u in units:
        if u.tokens > max_tokens:
            # A single sentence/row bigger than the whole budget: flush what we
            # have, then keep it whole as its own chunk (with its table header).
            current, carried = detach_header(current, u)
            if current:
                chunks.append(current)
            # The header goes with the row: the moved originals, else copies.
            chunks.append((carried or header_copy(u)) + [u])
            current, current_tokens = [], 0
            continue

        if current and current_tokens + u.tokens > max_tokens:
            # Budget would overflow — close the current chunk here.
            # A closing chunk that ends on this table's bare header gives it up.
            current, carried = detach_header(current, u)
            # Emit what is left, unless the header was all there was.
            if current:
                chunks.append(current)
            if carried:
                current = carried
            elif u.table is not None:
                # A table row continues: open with the header, no sentence overlap.
                current = header_copy(u)
            else:
                # Prose continues: seed with trailing sentences (never rows).
                current = overlap(current)
            current_tokens = _tokens(current)

        # Add the unit to the (possibly fresh) accumulator.
        current.append(u)
        current_tokens += u.tokens

    # End of page: flush whatever is left. Chunks never carry into the next page.
    if current:
        chunks.append(current)
    return chunks


def chunk_document(
    doc: ParsedDocument,
    document_id: str,
    max_tokens: int | None = None,
    overlap_fraction: float | None = None,
    min_tokens: int | None = None,
) -> list[Chunk]:
    """Chunk a parsed document into page-anchored, token-budgeted chunks."""
    # Explicit args win; otherwise use configured defaults.
    max_tokens = max_tokens or settings.chunk_max_tokens
    overlap_fraction = overlap_fraction or settings.chunk_overlap_fraction
    # 0 is a valid explicit minimum (merging off), so test for None, not falsiness.
    min_tokens = settings.chunk_min_tokens if min_tokens is None else min_tokens
    # Never let the minimum approach the budget: with a small budget a full
    # chunk could itself count as "tiny" and everything would merge.
    min_tokens = min(min_tokens, max_tokens // 4)
    # Overlap expressed in tokens, e.g. 512 * 0.15 ≈ 76 tokens.
    overlap_tokens = int(max_tokens * overlap_fraction)

    # gpt-4o's encoding is a stable, model-agnostic-enough token yardstick.
    enc = tiktoken.encoding_for_model("gpt-4o")
    chunks: list[Chunk] = []
    chunk_idx = 0

    # Running character offset of the current page within doc.full_text
    # (which joins pages with "\n\n" — see ParsedDocument.__post_init__).
    full_text_offset = 0

    for page in doc.pages:
        # Empty pages still advance the offset to keep char positions honest.
        if not page.text.strip():
            full_text_offset += len(page.text) + 2  # account for \n\n join
            continue

        # The page's first heading labels every chunk from this page.
        current_header = page.headers[0] if page.headers else ""

        # Units -> budgeted chunks -> tiny chunks folded into neighbours.
        units = _page_units(page.text, enc)
        packed = _merge_tiny(_page_chunks(units, max_tokens, overlap_tokens), min_tokens)

        for group in packed:
            # Offsets come from the first and last units that are not header
            # copies — a continuation chunk's citation starts at its first row.
            own = [u for u in group if u.origin is None] or group
            char_start = full_text_offset + own[0].start
            char_end = full_text_offset + own[-1].start + len(own[-1].text)
            chunks.append(
                _make_chunk(
                    _join(group), doc.filename, document_id, page.page_number,
                    char_start, current_header, chunk_idx, char_end=char_end,
                )
            )
            chunk_idx += 1

        # Advance the offset past this page plus the "\n\n" join.
        full_text_offset += len(page.text) + 2

    log.info("chunked document", filename=doc.filename, num_chunks=len(chunks))
    return chunks
