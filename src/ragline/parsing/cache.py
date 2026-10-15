"""Parse cache — ParsedDocuments stored by content hash, so parsing can run ahead of ingest.

Parsing is CPU-bound and needs no GPU; the rest of ingestion (embedding, KG
extraction) needs the pod. Caching the parser's output lets `scripts/preparse.py`
parse a whole corpus in separate processes beforehand, and ingestion then only
reads the result (see docs/eval/parse-cache-plan.md).

Layout: <PARSE_CACHE_DIR>/<fingerprint>/<sha256 of the file bytes>.json.gz

The fingerprint names everything that changes parser output: the cache format,
the parsing libraries' versions (pymupdf4llm, pymupdf, python-docx, openpyxl,
pandas), the OCR / layout-analysis settings, whether the OCR engine is actually
installed (and which version), and a hash of ragline's own parsing source. A
parser upgrade, a settings change, an edit to the parsing code, or a host
without Tesseract therefore misses the cache instead of serving stale or
OCR-less text.
The cache is off when PARSE_CACHE_DIR is empty, which is the default.
"""

import dataclasses
import functools
import gzip
import hashlib
import json
import os
import uuid
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import structlog

from ragline.parsing.models import PageContent, ParsedDocument

log = structlog.get_logger()

# Bump when the stored JSON shape changes; old entries then simply miss.
CACHE_FORMAT = 1


def _pkg_version(name: str) -> str:
    """Installed version of a package, or "absent" when it is not installed."""
    try:
        return version(name)
    except PackageNotFoundError:
        return "absent"


# The parser modules whose code shapes the output (this module is excluded:
# changing how entries are stored is what CACHE_FORMAT is for).
_PARSER_SOURCES = ("base.py", "docx_parser.py", "excel_parser.py", "layout_analyzer.py",
                   "models.py", "pdf_parser.py", "registry.py")


@functools.lru_cache(maxsize=1)
def ocr_engine() -> str:
    """The Tesseract version the PDF parser's OCR fallback would use, or "absent".

    Cached per process: it shells out to tesseract once.
    """
    try:
        import pytesseract

        return str(pytesseract.get_tesseract_version())
    except Exception:
        # Not installed (Python package or binary): scanned pages get no OCR.
        return "absent"


@functools.lru_cache(maxsize=1)
def parser_source_hash() -> str:
    """Hash of ragline's parsing source, so code edits invalidate old parses."""
    h = hashlib.sha256()
    here = Path(__file__).parent
    for name in _PARSER_SOURCES:
        # Name and bytes of each file, in a fixed order.
        h.update(name.encode())
        h.update((here / name).read_bytes())
    return h.hexdigest()[:16]


def parser_identity() -> dict:
    """Everything that changes what the parsers produce, as a plain dict."""
    # Deferred import: settings read .env, which tests may override first.
    from ragline.config import settings

    return {
        "format": CACHE_FORMAT,
        "pymupdf4llm": _pkg_version("pymupdf4llm"),
        "pymupdf": _pkg_version("pymupdf"),
        "python-docx": _pkg_version("python-docx"),
        "openpyxl": _pkg_version("openpyxl"),
        "pandas": _pkg_version("pandas"),
        "enable_ocr_fallback": settings.enable_ocr_fallback,
        "enable_layout_analysis": settings.enable_layout_analysis,
        # Only meaningful with the fallback on; recorded either way for simplicity.
        "ocr_engine": ocr_engine(),
        "parser_source": parser_source_hash(),
    }


def fingerprint(identity: dict | None = None) -> str:
    """Short, stable hash of the parser identity (the cache namespace)."""
    ident = identity if identity is not None else parser_identity()
    # sort_keys makes the hash independent of dict ordering.
    return hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()[:12]


def file_sha256(path: Path) -> str:
    """SHA-256 of a file's bytes, read in blocks so large manuals stay cheap on memory."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        # 1 MiB blocks until EOF.
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class ParseCache:
    """A directory of cached ParsedDocuments under one parser fingerprint."""

    def __init__(self, root: str | Path, identity: dict | None = None):
        # The namespace is fixed at construction: one cache object, one parser identity.
        self.identity = identity if identity is not None else parser_identity()
        self.dir = Path(root) / fingerprint(self.identity)

    def _entry(self, sha: str) -> Path:
        """Where the entry for a given content hash lives."""
        return self.dir / f"{sha}.json.gz"

    def has(self, sha: str) -> bool:
        """True when a parse for these bytes is already cached."""
        return self._entry(sha).is_file()

    def get(self, sha: str, filename: str) -> ParsedDocument | None:
        """The cached parse for these bytes, or None (missing or unreadable).

        `filename` replaces the stored one: identical bytes may arrive under a
        different name, and the name becomes the chunks' citation source.
        """
        entry = self._entry(sha)
        if not entry.is_file():
            return None
        try:
            with gzip.open(entry, "rt", encoding="utf-8") as fh:
                data = json.load(fh)
            # Rebuild the dataclasses; full_text was stored, so it is kept as is.
            pages = [PageContent(**p) for p in data["pages"]]
            return ParsedDocument(filename=filename, file_type=data["file_type"],
                                  pages=pages, full_text=data.get("full_text", ""))
        except Exception as exc:
            # A corrupt or foreign entry is a miss, never a failed document.
            log.warning("parse cache entry unreadable, parsing instead", entry=str(entry), error=str(exc))
            return None

    def put(self, sha: str, doc: ParsedDocument) -> None:
        """Store a parse atomically (temp file + rename), so readers never see half a file."""
        self.dir.mkdir(parents=True, exist_ok=True)
        # Record what the namespace means, once, for humans inspecting the cache.
        ident_file = self.dir / "fingerprint.json"
        if not ident_file.exists():
            ident_file.write_text(json.dumps(self.identity, indent=1))
        entry = self._entry(sha)
        # Unique temp name per writer (threads share a pid), so parallel writers cannot collide.
        tmp = entry.with_name(f"{entry.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(dataclasses.asdict(doc), fh)
        os.replace(tmp, entry)


def configured_cache() -> ParseCache | None:
    """The cache PARSE_CACHE_DIR points at, or None when caching is off."""
    from ragline.config import settings

    return ParseCache(settings.parse_cache_dir) if settings.parse_cache_dir else None


def parse_with_cache(file_path: Path, parse, cache: ParseCache | None) -> ParsedDocument:
    """Parse `file_path` via `parse(file_path)`, reading and filling `cache` when given."""
    if cache is None:
        return parse(file_path)
    sha = file_sha256(file_path)
    hit = cache.get(sha, file_path.name)
    if hit is not None:
        log.info("parse cache hit", file=file_path.name)
        return hit
    doc = parse(file_path)
    try:
        cache.put(sha, doc)
    except Exception as exc:
        # Any write problem (full or read-only disk, unexpected data) must not fail ingestion.
        log.warning("parse cache write failed", file=file_path.name, error=str(exc))
    return doc
