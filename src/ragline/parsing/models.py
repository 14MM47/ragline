"""Parsing data models — the normalized output every parser produces.

Ported from raggles. Whatever the input format, downstream stages (chunking,
ingestion) only ever see these two dataclasses.
"""

from dataclasses import dataclass, field


@dataclass
class PageContent:
    """One page (or page-equivalent unit) of a parsed document."""

    # 1-indexed page number — this is what citations point back to.
    page_number: int
    # The page's extracted text (markdown for PDFs).
    text: str
    # Markdown headings found on the page; the first becomes the chunk's
    # section_header, which citations display.
    headers: list[str] = field(default_factory=list)
    # Markdown tables found on the page (kept for future table-aware features).
    tables: list[str] = field(default_factory=list)
    # Layout-analysis outputs: detected column count and (when multi-column)
    # the reading-order-corrected text that replaced the raw extraction.
    column_count: int = 1
    reading_order_text: str = ""


@dataclass
class ParsedDocument:
    """A fully parsed document: ordered pages plus concatenated full text."""

    # Original filename (e.g. "acs880_manual.pdf") — carried into every chunk
    # as source_file, the citation's display name.
    filename: str
    # Normalized type tag: "pdf" | "docx" | "xlsx".
    file_type: str
    # Pages in document order.
    pages: list[PageContent]
    # Concatenated text of all pages; auto-built when not supplied.
    full_text: str = ""

    def __post_init__(self):
        # Join pages with blank lines when the caller didn't supply full_text.
        # NOTE: chunking's char-offset bookkeeping assumes this exact
        # "\n\n" join — keep the two in sync.
        if not self.full_text:
            self.full_text = "\n\n".join(p.text for p in self.pages)
