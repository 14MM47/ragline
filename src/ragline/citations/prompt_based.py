"""format_sources_prompt — numbered [Source i] blocks for the LLM prompt.

Ported verbatim from raggles. The 1-based position of each chunk in the list
is the LOAD-BEARING link of the citation chain: the LLM cites "[Source 3]",
and extract_citations maps 3 back to chunks[2] — so the chunk list passed
here MUST be the same list, in the same order, passed to extract_citations.
"""

from ragline.chunking.models import Chunk


def format_sources_prompt(chunks: list[Chunk]) -> str:
    """Format retrieved chunks as numbered sources for the LLM prompt."""
    source_blocks = []
    for i, chunk in enumerate(chunks, start=1):
        # Human-readable header: file, page(s), optional section.
        header_parts = [f"File: {chunk.source_file}"]
        if chunk.page_start == chunk.page_end:
            header_parts.append(f"Page: {chunk.page_start}")
        else:
            header_parts.append(f"Pages: {chunk.page_start}-{chunk.page_end}")
        if chunk.section_header:
            header_parts.append(f"Section: {chunk.section_header}")

        header = ", ".join(header_parts)
        # The quoted text is the chunk verbatim — the LLM answers from this.
        source_blocks.append(f'[Source {i}] ({header})\n"{chunk.text}"')

    return "\n\n".join(source_blocks)
