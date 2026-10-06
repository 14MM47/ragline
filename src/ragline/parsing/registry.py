"""Parser registry — maps file extensions to parser classes.

Ported from raggles. To support a new format (or swap the PDF parser for
Docling/MinerU in the modernization phase), register it here — nothing else
in the pipeline changes.
"""

from pathlib import Path

from ragline.parsing.base import BaseParser
from ragline.parsing.docx_parser import DocxParser
from ragline.parsing.excel_parser import ExcelParser
from ragline.parsing.pdf_parser import PdfParser

# Extension (lowercase, with dot) -> parser class.
_PARSERS: dict[str, type[BaseParser]] = {
    ".pdf": PdfParser,
    ".docx": DocxParser,
    ".xlsx": ExcelParser,
    # NOTE: legacy binary ".xls" is intentionally NOT registered — ExcelParser
    # reads via openpyxl, which only handles OOXML .xlsx. Advertising .xls made
    # every such upload silently fail (status="error"). Re-add here together
    # with the xlrd engine (see ExcelParser) if legacy .xls support is needed.
}

# Lazily-created singleton instance per extension (parsers are stateless).
_instances: dict[str, BaseParser] = {}


def get_parser(file_path: Path) -> BaseParser:
    """Return the parser for a file, raising ValueError for unsupported types.

    Batch ingestion catches that ValueError to mark files skipped_unsupported
    rather than failing the whole batch.
    """
    ext = file_path.suffix.lower()
    if ext not in _PARSERS:
        raise ValueError(f"Unsupported file type: {ext}")
    # Create the instance on first use, then reuse it.
    if ext not in _instances:
        _instances[ext] = _PARSERS[ext]()
    return _instances[ext]


def supported_extensions() -> list[str]:
    """List supported extensions (used by upload validation and the UI)."""
    return list(_PARSERS.keys())
