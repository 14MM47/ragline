"""Layout analysis — detects columns, headers/footers, and reading order.

Ported from raggles. Uses only fitz (pymupdf) block bounding boxes — no extra
dependencies. Two jobs in ragline:
  1. classify page-header/page-footer blocks (datasheets repeat these on every
     page; they are noise for retrieval),
  2. detect 2-column pages and produce reading-order-corrected text so
     sentences aren't interleaved across columns.
"""

from dataclasses import dataclass, field
from enum import Enum

import structlog

log = structlog.get_logger()


class RegionType(str, Enum):
    """Coarse classification of a text block's role on the page."""

    HEADER = "header"            # section heading within the body
    BODY = "body"                # normal paragraph text
    SIDEBAR = "sidebar"          # narrow edge column (specs boxes, notes)
    FOOTNOTE = "footnote"        # small text near the bottom of the body
    CAPTION = "caption"          # figure/table caption
    TABLE = "table"              # pipe-delimited table text
    PAGE_HEADER = "page_header"  # repeated banner at the very top
    PAGE_FOOTER = "page_footer"  # repeated banner at the very bottom


@dataclass
class LayoutBlock:
    """One classified text block from a page."""

    text: str
    # (x0, y0, x1, y1) normalised to [0, 1] page coordinates.
    bbox: tuple[float, float, float, float]
    region_type: RegionType
    # Position of this block in corrected reading order (0-based).
    reading_order: int = 0
    # Which column the block sits in (0 = left, 1 = right) on 2-column pages.
    column_index: int = 0
    page_number: int = 1


@dataclass
class PageLayout:
    """The analyzer's result for one page."""

    page_number: int
    blocks: list[LayoutBlock] = field(default_factory=list)
    column_count: int = 1
    has_header: bool = False
    has_footer: bool = False

    @property
    def reading_order_text(self) -> str:
        """All block text joined in corrected reading order."""
        # Sort by the assigned order, drop empty blocks, join as paragraphs.
        sorted_blocks = sorted(self.blocks, key=lambda b: b.reading_order)
        return "\n\n".join(b.text.strip() for b in sorted_blocks if b.text.strip())


class LayoutAnalyzer:
    """Analyses PDF page layout using fitz block bboxes."""

    def __init__(self, header_threshold: float = 0.08, footer_threshold: float = 0.92):
        # Blocks whose vertical midpoint is above/below these fractions of the
        # page are classified page_header / page_footer.
        self.header_threshold = header_threshold
        self.footer_threshold = footer_threshold

    def analyze_page(self, fitz_page) -> PageLayout:
        """Analyse a fitz.Page and return a PageLayout with classified blocks.

        Never raises: any failure logs a warning and returns an empty layout,
        so a malformed page can't break document ingestion.
        """
        try:
            # Page dimensions for bbox normalisation (guard against zero).
            page_rect = fitz_page.rect
            page_width = page_rect.width or 1.0
            page_height = page_rect.height or 1.0

            # fitz's dict extraction gives every block with bbox + line spans.
            block_dict = fitz_page.get_text("dict")
            raw_blocks = block_dict.get("blocks", [])

            layout_blocks: list[LayoutBlock] = []

            for block in raw_blocks:
                # Type 0 = text block; images and drawings are skipped.
                if block.get("type", 0) != 0:
                    continue

                bbox = block.get("bbox", (0, 0, 0, 0))
                x0, y0, x1, y1 = bbox

                # Rebuild the block's text from its line spans.
                text = ""
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text += span.get("text", "")
                    text += "\n"
                text = text.strip()

                # Empty blocks carry no signal — skip.
                if not text:
                    continue

                # Normalise the bbox to [0, 1] so thresholds are size-independent.
                norm_bbox = (
                    x0 / page_width,
                    y0 / page_height,
                    x1 / page_width,
                    y1 / page_height,
                )

                # Classify and collect.
                region_type = self._classify_region(norm_bbox, text)
                layout_blocks.append(LayoutBlock(
                    text=text,
                    bbox=norm_bbox,
                    region_type=region_type,
                    page_number=fitz_page.number + 1,  # fitz pages are 0-indexed
                ))

            # Column detection only considers body text — sidebars/captions
            # would distort the midpoint distribution.
            body_blocks = [b for b in layout_blocks if b.region_type == RegionType.BODY]
            column_count = self._detect_columns(body_blocks)

            # On multi-column pages, tag each body block with its column.
            if column_count > 1:
                self._assign_columns(body_blocks, column_count)

            # Compute the corrected reading order across all blocks.
            self._assign_reading_order(layout_blocks, column_count)

            # Presence flags for the page-level result.
            has_header = any(b.region_type == RegionType.PAGE_HEADER for b in layout_blocks)
            has_footer = any(b.region_type == RegionType.PAGE_FOOTER for b in layout_blocks)

            return PageLayout(
                page_number=fitz_page.number + 1,
                blocks=layout_blocks,
                column_count=column_count,
                has_header=has_header,
                has_footer=has_footer,
            )

        except Exception as e:
            # Degrade gracefully — the caller falls back to raw extracted text.
            log.warning("layout analysis failed for page", page=getattr(fitz_page, "number", "?"), error=str(e))
            return PageLayout(page_number=getattr(fitz_page, "number", 0) + 1)

    def _classify_region(
        self,
        norm_bbox: tuple[float, float, float, float],
        text: str,
    ) -> RegionType:
        """Heuristic classification of one block from position + content."""
        x0, y0, x1, y1 = norm_bbox
        text_lower = text.lower()
        block_width = x1 - x0
        mid_y = (y0 + y1) / 2

        # Page header/footer purely by vertical position.
        if mid_y < self.header_threshold:
            return RegionType.PAGE_HEADER
        if mid_y > self.footer_threshold:
            return RegionType.PAGE_FOOTER

        # Table: multiple pipe characters is a strong markdown-table signal.
        if "|" in text and text.count("|") >= 2:
            return RegionType.TABLE

        # Caption: short text mentioning figure/table keywords.
        if len(text) < 120 and any(kw in text_lower for kw in ["figure", "fig.", "table", "chart", "diagram"]):
            return RegionType.CAPTION

        # Footnote: smallish text low on the page, not full width.
        if mid_y > 0.75 and len(text) < 200 and block_width < 0.85:
            return RegionType.FOOTNOTE

        # Sidebar: narrow block hugging the left or right page edge.
        if block_width < 0.25 and (x0 < 0.1 or x1 > 0.9):
            return RegionType.SIDEBAR

        # Section header: short line that is ALL CAPS or ends with a colon.
        if len(text) < 80 and (text == text.upper() or text.endswith(":")):
            return RegionType.HEADER

        # Everything else is normal body text.
        return RegionType.BODY

    def _detect_columns(self, body_blocks: list[LayoutBlock]) -> int:
        """Detect column count by finding a horizontal gap between block midpoints."""
        # Too few blocks to establish a pattern — assume single column.
        if len(body_blocks) < 4:
            return 1

        # Horizontal midpoints of all body blocks, sorted left to right.
        midpoints = [(b.bbox[0] + b.bbox[2]) / 2 for b in body_blocks]
        midpoints.sort()

        if not midpoints:
            return 1

        # A gap > 0.15 page-widths whose centre lies in the middle third of
        # the page indicates a 2-column layout's gutter.
        middle_gap = False
        for i in range(len(midpoints) - 1):
            gap = midpoints[i + 1] - midpoints[i]
            avg_mid = (midpoints[i] + midpoints[i + 1]) / 2
            if gap > 0.15 and 0.3 < avg_mid < 0.7:
                middle_gap = True
                break

        # Only 1 vs 2 columns are distinguished (3+ columns are rare in
        # datasheets and would need a clustering approach).
        return 2 if middle_gap else 1

    def _assign_columns(self, body_blocks: list[LayoutBlock], column_count: int) -> None:
        """Tag body blocks with column 0 (left) or 1 (right) by x-midpoint."""
        if column_count < 2:
            return
        for block in body_blocks:
            mid_x = (block.bbox[0] + block.bbox[2]) / 2
            block.column_index = 0 if mid_x < 0.5 else 1

    def _assign_reading_order(self, blocks: list[LayoutBlock], column_count: int) -> None:
        """Assign reading_order: top→bottom within each column, columns left→right.

        Page headers/footers are pushed to the end of the order so repeated
        banners never interrupt body text mid-flow.
        """
        # Separate main content from repeated page furniture.
        main_blocks = [b for b in blocks if b.region_type not in (RegionType.PAGE_HEADER, RegionType.PAGE_FOOTER)]
        meta_blocks = [b for b in blocks if b.region_type in (RegionType.PAGE_HEADER, RegionType.PAGE_FOOTER)]

        if column_count >= 2:
            # Whole left column first (top→bottom), then the right column.
            sorted_main = sorted(main_blocks, key=lambda b: (b.column_index, b.bbox[1]))
        else:
            # Single column: plain top→bottom.
            sorted_main = sorted(main_blocks, key=lambda b: b.bbox[1])

        # Number the main blocks in their corrected order.
        for i, block in enumerate(sorted_main):
            block.reading_order = i

        # Headers/footers come after all main content.
        offset = len(sorted_main)
        for i, block in enumerate(sorted(meta_blocks, key=lambda b: b.bbox[1])):
            block.reading_order = offset + i
