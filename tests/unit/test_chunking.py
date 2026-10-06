"""Structural chunking tests — the invariants citations depend on."""

from ragline.chunking.models import Chunk
from ragline.chunking.structural import chunk_document
from ragline.parsing.models import PageContent, ParsedDocument


def _make_doc(text: str, filename: str = "test.pdf") -> ParsedDocument:
    """One-page document with a known header, for concise test setup."""
    return ParsedDocument(
        filename=filename,
        file_type="pdf",
        pages=[PageContent(page_number=1, text=text, headers=["Introduction"])],
    )


def test_basic_chunking():
    """Long text splits into multiple chunks, all carrying source identity."""
    text = "This is a test sentence. " * 100
    doc = _make_doc(text)
    chunks = chunk_document(doc, document_id="doc-1", max_tokens=50)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.source_file == "test.pdf"
        assert chunk.document_id == "doc-1"
        assert chunk.page_start == 1


def test_single_page_metadata():
    """Short text yields one chunk with header and exact page span."""
    doc = _make_doc("Short text.")
    chunks = chunk_document(doc, document_id="doc-1")
    assert len(chunks) == 1
    assert chunks[0].section_header == "Introduction"
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 1


def test_multi_page():
    """Chunks never span pages — each page's text stays on its page number."""
    doc = ParsedDocument(
        filename="multi.pdf",
        file_type="pdf",
        pages=[
            PageContent(page_number=1, text="Page one content.", headers=["Intro"]),
            PageContent(page_number=2, text="Page two content.", headers=["Body"]),
        ],
    )
    chunks = chunk_document(doc, document_id="doc-2")
    assert len(chunks) >= 2
    pages = {c.page_start for c in chunks}
    assert pages == {1, 2}


def test_context_prefix():
    """The embedding prefix names file, page, and section."""
    chunk = Chunk(
        text="test",
        source_file="report.pdf",
        document_id="1",
        page_start=5,
        page_end=5,
        char_start=0,
        char_end=4,
        section_header="Revenue",
    )
    assert "report.pdf" in chunk.context_prefix
    assert "Page: 5" in chunk.context_prefix
    assert "Revenue" in chunk.context_prefix


def test_empty_page_skipped():
    """Blank pages produce no chunks but don't derail later pages."""
    doc = ParsedDocument(
        filename="test.pdf",
        file_type="pdf",
        pages=[
            PageContent(page_number=1, text="", headers=[]),
            PageContent(page_number=2, text="Real content here.", headers=["Section"]),
        ],
    )
    chunks = chunk_document(doc, document_id="doc-3")
    assert len(chunks) == 1
    assert chunks[0].page_start == 2
