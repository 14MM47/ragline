"""ExcelParser tests — sheet-per-page structure and row-text rendering."""

import tempfile
from pathlib import Path

import pandas as pd

from ragline.parsing.excel_parser import ExcelParser


def test_excel_parse():
    """A one-sheet workbook parses into one page with labelled rows."""
    df = pd.DataFrame({"Name": ["Alice", "Bob"], "Revenue": [100, 200]})

    # Write a real .xlsx to a temp file for the parser to read.
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        df.to_excel(f.name, index=False, sheet_name="Sales")
        path = Path(f.name)

    parser = ExcelParser()
    result = parser.parse(path)

    assert result.filename == path.name
    assert result.file_type in ("xlsx", "xls")
    assert len(result.pages) == 1
    # The sheet name doubles as the page's header (citation section).
    assert "Sales" in result.pages[0].headers
    # Row values and column names both appear in the rendered text.
    assert "Alice" in result.pages[0].text
    assert "Revenue" in result.pages[0].text

    path.unlink()


def test_multi_sheet():
    """Each non-empty sheet becomes its own page."""
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        with pd.ExcelWriter(f.name, engine="openpyxl") as writer:
            pd.DataFrame({"A": [1]}).to_excel(writer, sheet_name="Sheet1", index=False)
            pd.DataFrame({"B": [2]}).to_excel(writer, sheet_name="Sheet2", index=False)
        path = Path(f.name)

    parser = ExcelParser()
    result = parser.parse(path)
    assert len(result.pages) == 2

    path.unlink()
