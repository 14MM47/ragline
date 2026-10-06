"""Chunk — THE citation ground truth of the whole system.

Ported from raggles minus the playground fields (parent-child, propositions,
ColPali). Every chunk carries its full source identity (file, document id,
page span, char offsets, section). This identity travels: into the Qdrant
payload at ingest, back out at retrieval, into the prompt as a numbered
[Source N] block, and finally into the Citation objects the UI renders.
The LLM never invents any of it — DO NOT alter these field semantics.
"""

from dataclasses import dataclass


@dataclass
class Chunk:
    # The chunk's text content (what gets embedded and shown to the LLM).
    text: str
    # Original filename, e.g. "acs880_manual.pdf" — the citation display name.
    source_file: str
    # Metadata-DB Document.id this chunk belongs to — the citation link key.
    document_id: str
    # 1-indexed page span the text came from (start == end for single-page
    # chunks, which structural chunking always produces).
    page_start: int
    page_end: int
    # Character offsets into the document's full_text (headroom for future
    # exact-highlight features).
    char_start: int
    char_end: int
    # First heading on the chunk's page — shown in the citation sidebar.
    section_header: str = ""
    # 0-based position of this chunk within its document.
    chunk_index: int = 0
    # Stable ID; used as the vector-store point ID when set.
    chunk_id: str = ""

    @property
    def context_prefix(self) -> str:
        """Human-readable source tag, e.g. "[Source: x.pdf | Page: 3 | Section: Specs]".

        Prepended to chunk text before embedding so the vector encodes where
        the text came from as well as what it says.
        """
        parts = [f"Source: {self.source_file}"]
        if self.page_start == self.page_end:
            parts.append(f"Page: {self.page_start}")
        else:
            parts.append(f"Pages: {self.page_start}-{self.page_end}")
        if self.section_header:
            parts.append(f"Section: {self.section_header}")
        return f"[{' | '.join(parts)}]"
