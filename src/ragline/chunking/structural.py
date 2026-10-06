"""Structural chunking — token-budgeted chunks at sentence boundaries.

Ported from raggles (its default and best-validated strategy; the semantic /
proposition alternatives were playground experiments and are not ported).

Guarantees the citation machinery relies on:
  * a chunk NEVER spans pages (page_start == page_end always), so a citation's
    page number is exact;
  * chunks respect the token budget except single sentences that alone exceed
    it (kept whole as their own chunk rather than split mid-sentence);
  * consecutive chunks overlap by ~overlap_fraction of the budget so answers
    that straddle a boundary are still retrievable.
"""

import re

import structlog
import tiktoken

from ragline.chunking.models import Chunk
from ragline.config import settings
from ragline.parsing.models import ParsedDocument

log = structlog.get_logger()


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
) -> Chunk:
    """Build one page-anchored Chunk (char_end derived from the text length).

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
        char_end=char_start + len(text),
        section_header=section_header,
        chunk_index=chunk_index,
    )


def _split_at_sentence_boundaries(text: str) -> list[str]:
    """Split text into sentences, keeping the terminating punctuation attached."""
    # Split after ., ! or ? followed by whitespace; simple but robust across
    # the markdown-ish text our parsers produce.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s for s in sentences if s.strip()]


def chunk_document(
    doc: ParsedDocument,
    document_id: str,
    max_tokens: int | None = None,
    overlap_fraction: float | None = None,
) -> list[Chunk]:
    """Chunk a parsed document into page-anchored, token-budgeted chunks."""
    # Explicit args win; otherwise use configured defaults.
    max_tokens = max_tokens or settings.chunk_max_tokens
    overlap_fraction = overlap_fraction or settings.chunk_overlap_fraction
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
        page_text = page.text.strip()
        # Empty pages still advance the offset to keep char positions honest.
        if not page_text:
            full_text_offset += len(page.text) + 2  # account for \n\n join
            continue

        # The page's first heading labels every chunk from this page.
        current_header = page.headers[0] if page.headers else ""
        sentences = _split_at_sentence_boundaries(page_text)

        # Accumulator for the chunk currently being built.
        current_chunk_sentences: list[str] = []
        current_tokens = 0

        for sentence in sentences:
            sentence_tokens = _count_tokens(sentence, enc)

            if sentence_tokens > max_tokens:
                # A single sentence bigger than the whole budget (huge table
                # rows, spec lists). Flush what we have, then keep the
                # oversized sentence whole as its own chunk.
                if current_chunk_sentences:
                    chunk_text = " ".join(current_chunk_sentences)
                    # Locate the chunk in the full text via its first sentence.
                    char_start = full_text_offset + page_text.find(current_chunk_sentences[0])
                    chunks.append(
                        _make_chunk(
                            chunk_text, doc.filename, document_id, page.page_number,
                            char_start, current_header, chunk_idx,
                        )
                    )
                    chunk_idx += 1
                    current_chunk_sentences = []
                    current_tokens = 0

                # The oversized sentence as a standalone chunk.
                chunks.append(
                    _make_chunk(
                        sentence, doc.filename, document_id, page.page_number,
                        full_text_offset + page_text.find(sentence), current_header, chunk_idx,
                    )
                )
                chunk_idx += 1
                continue

            if current_tokens + sentence_tokens > max_tokens:
                # Budget would overflow — close the current chunk here.
                chunk_text = " ".join(current_chunk_sentences)
                char_start = full_text_offset + page_text.find(current_chunk_sentences[0])
                chunks.append(
                    _make_chunk(
                        chunk_text, doc.filename, document_id, page.page_number,
                        char_start, current_header, chunk_idx,
                    )
                )
                chunk_idx += 1

                # Seed the next chunk with trailing sentences from this one
                # until the overlap budget is spent (order preserved).
                overlap_sents: list[str] = []
                overlap_tok = 0
                for s in reversed(current_chunk_sentences):
                    s_tok = _count_tokens(s, enc)
                    if overlap_tok + s_tok > overlap_tokens:
                        break
                    overlap_sents.insert(0, s)
                    overlap_tok += s_tok

                current_chunk_sentences = overlap_sents
                current_tokens = overlap_tok

            # Add the sentence to the (possibly fresh) accumulator.
            current_chunk_sentences.append(sentence)
            current_tokens += sentence_tokens

        # End of page: flush whatever is left. Chunks never carry into the
        # next page — this is what keeps citation page numbers exact.
        if current_chunk_sentences:
            chunk_text = " ".join(current_chunk_sentences)
            char_start = full_text_offset + page_text.find(current_chunk_sentences[0])
            chunks.append(
                _make_chunk(
                    chunk_text, doc.filename, document_id, page.page_number,
                    char_start, current_header, chunk_idx,
                )
            )
            chunk_idx += 1

        # Advance the offset past this page plus the "\n\n" join.
        full_text_offset += len(page.text) + 2

    log.info("chunked document", filename=doc.filename, num_chunks=len(chunks))
    return chunks
