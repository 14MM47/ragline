"""ExcelParser — spreadsheets rendered as labelled row text, one sheet per page.

Ported from raggles. Each non-empty sheet becomes a "page" whose text lists
every row as "Column: value | Column: value" lines — a format that embeds and
retrieves well because column names sit right next to their values.
"""

from pathlib import Path

import pandas as pd
import structlog

from ragline.parsing.base import BaseParser
from ragline.parsing.models import PageContent, ParsedDocument

log = structlog.get_logger()


class ExcelParser(BaseParser):
    def parse(self, file_path: Path) -> ParsedDocument:
        log.info("parsing excel", file=file_path.name)
        # openpyxl reads OOXML .xlsx only (the sole registered Excel type).
        # Legacy binary .xls would need the xlrd engine and is not registered.
        xl = pd.ExcelFile(file_path, engine="openpyxl")
        pages: list[PageContent] = []

        # One PageContent per sheet; page_number = 1-based sheet position.
        for idx, sheet_name in enumerate(xl.sheet_names, start=1):
            df = xl.parse(sheet_name)
            # Sheets with no data rows carry no signal — skip.
            if df.empty:
                continue

            # Header lines identify the sheet and its columns for the LLM.
            lines = [f"Sheet: {sheet_name}"]
            lines.append(f"Columns: {', '.join(str(c) for c in df.columns)}")
            lines.append("")

            # Each row becomes one "Row N: col: val | col: val" line.
            for row_idx, row in df.iterrows():
                row_parts = []
                for col in df.columns:
                    val = row[col]
                    # NaN cells are omitted rather than rendered as "nan".
                    if pd.notna(val):
                        row_parts.append(f"{col}: {val}")
                if row_parts:
                    lines.append(f"Row {row_idx}: {' | '.join(row_parts)}")

            pages.append(
                PageContent(
                    page_number=idx,
                    text="\n".join(lines),
                    # Sheet name doubles as the section header for citations.
                    headers=[sheet_name],
                )
            )

        # file_type reflects the actual extension ("xlsx" or "xls").
        ext = file_path.suffix.lstrip(".")
        return ParsedDocument(filename=file_path.name, file_type=ext, pages=pages)
