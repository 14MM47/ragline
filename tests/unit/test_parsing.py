"""Parser registry tests — extension routing and unsupported-type rejection."""

from pathlib import Path

import pytest

from ragline.parsing.registry import get_parser, supported_extensions


def test_supported_extensions():
    """The three core formats must all be registered."""
    exts = supported_extensions()
    assert ".pdf" in exts
    assert ".docx" in exts
    assert ".xlsx" in exts


def test_get_parser_pdf():
    """.pdf routes to the PdfParser."""
    from ragline.parsing.pdf_parser import PdfParser

    parser = get_parser(Path("test.pdf"))
    assert isinstance(parser, PdfParser)


def test_get_parser_excel():
    """.xlsx routes to the ExcelParser."""
    from ragline.parsing.excel_parser import ExcelParser

    parser = get_parser(Path("test.xlsx"))
    assert isinstance(parser, ExcelParser)


def test_unsupported_extension():
    """Unknown extensions raise ValueError (batch upload reports them as skipped)."""
    with pytest.raises(ValueError, match="Unsupported"):
        get_parser(Path("test.txt"))
