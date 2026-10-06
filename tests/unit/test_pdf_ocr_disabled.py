"""The PDF parser must disable pymupdf4llm's built-in layout-engine OCR.

pymupdf4llm >= 1.28 runs Tesseract on most pages by default. Measured over 549
pages of the real corpus it cost 1.9x the parse time and returned 21% LESS text
than with it off, because it REPLACES embedded text with worse OCR output — one
selection guide fell from 13,262 to 2,790 tokens. ragline does its own targeted
OCR for genuinely empty pages, so the engine pass must stay off. These tests pin
the kwarg on both call sites so a dependency bump or refactor can't reinstate it.
"""

import os

import pymupdf as fitz
import pymupdf4llm
import pytest

from ragline.parsing import pdf_parser
from ragline.parsing.pdf_parser import PdfParser

# Only the layout engine accepts use_ocr; legacy builds have no auto-OCR and
# would raise TypeError on the keyword, so the parser omits it there.
LAYOUT_ACTIVE = pdf_parser._LAYOUT_ENGINE_ACTIVE


def _one_page_pdf(path) -> None:
    """A minimal single-page PDF with enough text to skip the OCR fallback."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Rated supply voltage 24 V DC, tolerance +/- 10 percent.")
    doc.save(str(path))
    doc.close()


def test_main_extraction_disables_engine_ocr(tmp_path, monkeypatch):
    """The per-page extraction call must carry use_ocr=False."""
    pdf = tmp_path / "one.pdf"
    _one_page_pdf(pdf)

    seen: list[dict] = []

    def fake_to_markdown(path, **kwargs):
        # Record what the parser asked for, then return a realistic page chunk.
        seen.append(kwargs)
        return [{"text": "Rated supply voltage 24 V DC.", "metadata": {"page_number": 1}}]

    monkeypatch.setattr(pymupdf4llm, "to_markdown", fake_to_markdown)

    PdfParser().parse(pdf)

    assert seen, "to_markdown was never called"
    assert seen[0]["page_chunks"] is True
    if LAYOUT_ACTIVE:
        assert seen[0]["use_ocr"] is False
    else:
        # Legacy engine: the keyword must NOT be sent, or the call TypeErrors.
        assert "use_ocr" not in seen[0]


def test_fallback_extraction_disables_engine_ocr(tmp_path, monkeypatch):
    """The whole-document fallback path must disable OCR too."""
    pdf = tmp_path / "one.pdf"
    _one_page_pdf(pdf)

    seen: list[dict] = []

    def fake_to_markdown(path, **kwargs):
        seen.append(kwargs)
        # Empty page_chunks forces the parser onto its fallback branch; the
        # fallback call passes no page_chunks and expects a plain string.
        return [] if kwargs.get("page_chunks") else "Rated supply voltage 24 V DC."

    monkeypatch.setattr(pymupdf4llm, "to_markdown", fake_to_markdown)

    parsed = PdfParser().parse(pdf)

    assert len(seen) == 2, "expected a page-chunk call then a fallback call"
    assert parsed.pages[0].page_number == 1
    if LAYOUT_ACTIVE:
        assert seen[1]["use_ocr"] is False
    else:
        assert "use_ocr" not in seen[1]


# The real-corpus check is slow (~45 s) and needs the datasheet corpus, so it
# runs only under the integration flag — same gate the integration suite uses.
# RAGLINE_CORPUS_DIR points at the corpus root (default ./testdata, which is
# where scripts/fetch_corpus.py puts it).
_CORPUS_PDF = os.path.join(
    os.getenv("RAGLINE_CORPUS_DIR", "testdata"),
    "sensors/pepperl-fuchs/r20x-series/photoelectric_sensors_r10x_r20x_selection_guide.pdf",
)


@pytest.mark.skipif(
    os.getenv("RAGLINE_INTEGRATION") != "1" or not os.path.exists(_CORPUS_PDF),
    reason="needs RAGLINE_INTEGRATION=1 and the local test corpus",
)
def test_corpus_document_keeps_its_text():
    """The document hit worst by engine OCR must come back substantially intact.

    With engine OCR on this file yielded ~2,790 tokens (~11k chars); with it off
    it yields ~13,262 tokens (~53k chars). The 30k floor sits well clear of both.
    """
    parsed = PdfParser().parse(__import__("pathlib").Path(_CORPUS_PDF))
    total_chars = sum(len(p.text) for p in parsed.pages)
    assert total_chars > 30_000, f"text collapsed to {total_chars} chars — OCR back on?"
