"""PdfParser — PDF to per-page markdown, with OCR and layout fallbacks.

Ported from raggles. Pipeline per document:
  1. pymupdf4llm extracts every page as markdown (headings, tables preserved),
  2. pages with almost no text (< 50 chars) get a tesseract OCR pass — this
     catches scanned datasheets — gated by settings.enable_ocr_fallback,
  3. optional layout analysis fixes reading order on 2-column pages and is
     gated by settings.enable_layout_analysis.
"""

import os
import re
from pathlib import Path

import pymupdf4llm
import structlog

from ragline.parsing.base import BaseParser
from ragline.parsing.models import PageContent, ParsedDocument

log = structlog.get_logger()

# Each tesseract subprocess is kept single-threaded (OMP_THREAD_LIMIT=1).
# Parallelism comes from running multiple parse workers concurrently (the
# ingestion worker's thread pool), not from per-process threading. This gives
# predictable CPU usage: at most (cpu_count - 1) cores total.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

# Markdown heading lines ("# Title" ... "###### Title") — captured per page
# so the first heading can become the chunk's section_header.
HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
# Consecutive markdown table rows ("| a | b |").
TABLE_RE = re.compile(r"(?:^\|.+\|$\n?)+", re.MULTILINE)

# Pages with fewer than this many characters of extracted text are OCR candidates.
_OCR_THRESHOLD = 50

# pymupdf4llm >= 1.28 routes to_markdown through a document-layout engine that
# runs Tesseract on most pages by default (use_ocr=True). Measured over 549
# pages of the real corpus, that pass costs 1.9x the parse time and returns 21%
# LESS text than with it off: it REPLACES good embedded text with worse OCR
# output (one selection guide dropped from 13,262 to 2,790 tokens — a 79% loss).
# We do our own targeted OCR below, only for pages that are genuinely empty, so
# the engine's blanket pass is pure cost and pure damage. Older builds have no
# layout engine and route to the legacy parser, which does not accept the
# keyword at all — hence the capability check rather than an unconditional kwarg.
_LAYOUT_ENGINE_ACTIVE = bool(getattr(pymupdf4llm, "_use_layout", False))
# Extra kwargs applied to every to_markdown call: empty on legacy builds.
_MD_KWARGS: dict = {"use_ocr": False} if _LAYOUT_ENGINE_ACTIVE else {}


def _ocr_page(fitz_doc, page_idx: int) -> str:
    """Render a page to an image and run tesseract on it.

    Returns the OCR'd text, or an empty string if pytesseract/tesseract is
    not available or the call fails — OCR is always best-effort.
    """
    # Optional dependency: the [ocr] extra + the tesseract system binary.
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""

    try:
        # 200 dpi is a good OCR accuracy/speed trade-off for datasheets.
        pix = fitz_doc[page_idx].get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        return pytesseract.image_to_string(img).strip()
    except Exception as exc:
        log.warning("OCR failed for page", page_idx=page_idx, error=str(exc))
        return ""


class PdfParser(BaseParser):
    def parse(self, file_path: Path) -> ParsedDocument:
        # Import settings here (not module level) so tests can override config
        # and so this module imports cleanly without a .env present.
        from ragline.config import settings

        log.info("parsing pdf", file=file_path.name)

        # Main extraction: one markdown chunk per page, engine OCR disabled.
        page_chunks = pymupdf4llm.to_markdown(
            str(file_path), page_chunks=True, **_MD_KWARGS
        )

        # Open the fitz doc once; reused for OCR renders and layout analysis.
        # (`fitz` is PyMuPDF's old module name; importing it directly is deprecated.)
        import pymupdf as fitz
        fitz_doc = fitz.open(str(file_path))

        # Detect once whether pytesseract is importable, so we only emit the
        # "not installed" warning one time per document rather than per page.
        _tesseract_available: bool | None = None

        pages: list[PageContent] = []
        ocr_page_count = 0

        # pymupdf4llm's page metadata key AND indexing vary by version:
        # current builds emit `page_number` (1-indexed), older ones `page`
        # (0- or 1-indexed). Read whichever exists — silently defaulting a
        # missing key to 0 is exactly the bug that once collapsed every
        # citation to "p.1" (and pointed OCR/layout at the wrong fitz page).
        def _raw_page(meta: dict):
            return meta.get("page_number", meta.get("page", 0))

        # Decide the index offset ONCE for the whole document from the
        # smallest page value seen: if any page is 0 the source is 0-indexed
        # (every page needs +1); otherwise it is already 1-indexed. Deciding
        # per-page from the value itself is wrong — it would leave all but
        # the first page off by one on a 0-indexed build.
        raw_pages = [
            _raw_page(c.get("metadata", {}))
            for c in page_chunks
            if isinstance(_raw_page(c.get("metadata", {})), int)
        ]
        page_offset = 1 if raw_pages and min(raw_pages) == 0 else 0

        for chunk in page_chunks:
            text = chunk.get("text", "")
            meta = chunk.get("metadata", {})
            raw_page = _raw_page(meta)
            page_num = (raw_page if isinstance(raw_page, int) else int(raw_page)) + page_offset

            # --- OCR fallback for near-empty pages (scanned documents) ---
            if settings.enable_ocr_fallback and len(text.strip()) < _OCR_THRESHOLD:
                # Lazy availability check — only import once per document.
                if _tesseract_available is None:
                    try:
                        import pytesseract  # noqa: F401
                        _tesseract_available = True
                    except ImportError:
                        _tesseract_available = False
                        log.warning(
                            "image-based PDF detected but pytesseract is not installed; "
                            "install the [ocr] extra + tesseract-ocr for automatic OCR support",
                            file=file_path.name,
                        )

                if _tesseract_available:
                    # fitz pages are 0-indexed, hence page_num - 1.
                    ocr_text = _ocr_page(fitz_doc, page_num - 1)
                    if ocr_text:
                        text = ocr_text
                        ocr_page_count += 1

            # Pull headings/tables out of the (possibly OCR-replaced) text.
            headers = HEADING_RE.findall(text)
            tables = [m.strip() for m in TABLE_RE.findall(text)]

            # --- Layout analysis: fix reading order on multi-column pages ---
            column_count = 1
            reading_order_text = ""
            try:
                if settings.enable_layout_analysis:
                    from ragline.parsing.layout_analyzer import LayoutAnalyzer
                    fitz_page = fitz_doc[page_num - 1]
                    analyzer = LayoutAnalyzer()
                    layout = analyzer.analyze_page(fitz_page)
                    column_count = layout.column_count
                    if layout.column_count > 1:
                        # Multi-column page: replace the raw extraction with
                        # the column-aware reading order so sentences aren't
                        # interleaved across columns.
                        ro_text = layout.reading_order_text
                        if ro_text.strip():
                            reading_order_text = ro_text
                            text = ro_text
            except Exception as e:
                # Any layout failure just means we keep the default text.
                log.warning("layout analysis failed, using default text", page=page_num, error=str(e))

            pages.append(
                PageContent(
                    page_number=page_num,
                    text=text,
                    headers=headers,
                    tables=tables,
                    column_count=column_count,
                    reading_order_text=reading_order_text,
                )
            )

        # Done with the raw document handle.
        fitz_doc.close()

        # Surface how often OCR kicked in (a scale metric).
        if ocr_page_count:
            log.info("OCR fallback used", file=file_path.name, ocr_pages=ocr_page_count)

        if not pages:
            # Fallback: some PDFs defeat page chunking entirely — parse the
            # whole document as one markdown blob on "page 1".
            log.warning("page_chunks empty, falling back to full-document parse", file=file_path.name)
            md_text = pymupdf4llm.to_markdown(str(file_path), **_MD_KWARGS)
            pages = [PageContent(page_number=1, text=md_text)]

        return ParsedDocument(filename=file_path.name, file_type="pdf", pages=pages)
