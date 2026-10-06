"""PDF page-number propagation — regression guard for the "everything is
p.1" bug.

pymupdf4llm renamed its page-chunk metadata key (`page` -> `page_number`);
reading the old key with a 0 default made every page look 0-indexed, so the
offset heuristic shifted ALL pages to 1 — silently wrecking every citation's
page and pointing the OCR/layout steps at the wrong fitz page. This test
parses a real 3-page PDF and pins the 1..3 sequence.
"""

import pymupdf as fitz

from ragline.parsing.pdf_parser import PdfParser


def _make_pdf(path, n_pages: int) -> None:
    """A minimal n-page PDF, each page carrying distinct extractable text."""
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page()
        # Enough distinct text that pymupdf4llm keeps every page.
        page.insert_text((72, 72), f"Page {i + 1} content: widget spec {i + 1}00 mm.")
    doc.save(str(path))
    doc.close()


def test_pages_numbered_sequentially(tmp_path):
    """A 3-page PDF must come back as pages 1, 2, 3 — never all 1s."""
    pdf = tmp_path / "three_pages.pdf"
    _make_pdf(pdf, 3)

    parsed = PdfParser().parse(pdf)

    assert [p.page_number for p in parsed.pages] == [1, 2, 3]
    # And each page must carry its OWN text (the same bug aimed OCR/layout at
    # one fixed page, which could smear one page's content across others).
    for i, page in enumerate(parsed.pages, start=1):
        assert f"Page {i} content" in page.text
