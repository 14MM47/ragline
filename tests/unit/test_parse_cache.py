"""Parse cache — round trip, namespacing, worker use and the preparse script.

No real PDFs: the parser is a stub that counts its calls, so the tests show
exactly when the cache saves a parse and when it does not.
"""

import gzip
import importlib.util
from pathlib import Path

from ragline.parsing import cache as pc
from ragline.parsing.models import PageContent, ParsedDocument

IDENT = {"format": 1, "pymupdf4llm": "1.0", "pymupdf": "1.0", "python-docx": "1.0", "openpyxl": "1.0",
         "pandas": "1.0", "enable_ocr_fallback": True, "enable_layout_analysis": True, "ocr_engine": "5.3.4",
         "parser_source": "abc"}


def _doc(name: str = "a.pdf") -> ParsedDocument:
    """A two-page parsed document with headers and a table."""
    return ParsedDocument(filename=name, file_type="pdf", pages=[
        PageContent(page_number=1, text="# Title\nIntro.", headers=["Title"]),
        PageContent(page_number=2, text="|a|b|\n|---|---|\n|1|2|", tables=["|a|b|\n|---|---|\n|1|2|"],
                    column_count=2, reading_order_text="a b 1 2"),
    ])


class CountingParser:
    """Stands in for PdfParser.parse: returns a fixed document and counts calls."""

    def __init__(self):
        self.calls = 0

    def __call__(self, path: Path) -> ParsedDocument:
        self.calls += 1
        return _doc(path.name)


def test_round_trip(tmp_path):
    """put then get returns an equal document."""
    c = pc.ParseCache(tmp_path, IDENT)
    c.put("abc", _doc())
    assert c.has("abc") and c.get("abc", "a.pdf") == _doc()
    assert (c.dir / "fingerprint.json").is_file()


def test_get_uses_the_current_filename(tmp_path):
    """Same bytes under a new name: the citation name follows the file, not the cache."""
    c = pc.ParseCache(tmp_path, IDENT)
    c.put("abc", _doc("old.pdf"))
    assert c.get("abc", "new.pdf").filename == "new.pdf"


def test_fingerprint_changes_with_parser_and_settings():
    """Any parser version or parse setting change gives a different namespace."""
    base = pc.fingerprint(IDENT)
    assert pc.fingerprint(dict(IDENT)) == base
    for key, value in [("pymupdf4llm", "1.1"), ("pymupdf", "2.0"), ("enable_ocr_fallback", False),
                       ("enable_layout_analysis", False), ("format", 2), ("ocr_engine", "absent"),
                       ("parser_source", "def"), ("openpyxl", "9.9")]:
        assert pc.fingerprint({**IDENT, key: value}) != base


def test_missing_and_corrupt_entries_are_misses(tmp_path):
    """No entry, or an unreadable one, returns None rather than raising."""
    c = pc.ParseCache(tmp_path, IDENT)
    assert c.get("nope", "a.pdf") is None
    c.dir.mkdir(parents=True)
    (c.dir / "bad.json.gz").write_bytes(b"not gzip")
    assert c.get("bad", "a.pdf") is None
    with gzip.open(c.dir / "odd.json.gz", "wt") as fh:
        fh.write('{"unexpected": true}')
    assert c.get("odd", "a.pdf") is None


def test_parse_with_cache_hit_and_miss(tmp_path):
    """First call parses and stores; a second call with the same bytes reads the cache."""
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF fake bytes")
    c = pc.ParseCache(tmp_path / "cache", IDENT)
    parse = CountingParser()
    first = pc.parse_with_cache(f, parse, c)
    second = pc.parse_with_cache(f, parse, c)
    assert parse.calls == 1 and first == second
    # A different file with identical bytes is a hit too, under its own name.
    g = tmp_path / "copy.pdf"
    g.write_bytes(f.read_bytes())
    assert pc.parse_with_cache(g, parse, c).filename == "copy.pdf" and parse.calls == 1
    # Without a cache every call parses.
    pc.parse_with_cache(f, parse, None)
    assert parse.calls == 2


def test_real_identity_covers_engine_and_source():
    """The live identity names the OCR engine and a hash of the parser source."""
    ident = pc.parser_identity()
    assert ident["ocr_engine"] and len(ident["parser_source"]) == 16
    assert ident["format"] == pc.CACHE_FORMAT


def test_write_failure_never_fails_the_parse(tmp_path, monkeypatch):
    """A cache that cannot be written still returns the parse."""
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF unwritable")
    c = pc.ParseCache(tmp_path / "cache", IDENT)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(c, "put", boom)
    parse = CountingParser()
    assert pc.parse_with_cache(f, parse, c) == _doc("x.pdf") and parse.calls == 1
    # Not just OSError: any write error is contained.
    monkeypatch.setattr(c, "put", lambda *a, **k: (_ for _ in ()).throw(TypeError("odd field")))
    assert pc.parse_with_cache(f, parse, c) == _doc("x.pdf")


def test_parallel_writers_use_distinct_temp_files(tmp_path):
    """Two writers of the same entry at once never share a temp file."""
    import threading

    c = pc.ParseCache(tmp_path, IDENT)
    errors = []

    def write():
        try:
            for _ in range(20):
                c.put("same", _doc())
        except Exception as exc:  # pragma: no cover - the failure being guarded against
            errors.append(exc)

    threads = [threading.Thread(target=write) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and c.get("same", "a.pdf") == _doc()
    assert not list(c.dir.glob("*.tmp"))


def test_corrupt_entry_falls_back_to_parse(tmp_path):
    """A damaged entry is re-parsed and overwritten with a good one."""
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF other bytes")
    c = pc.ParseCache(tmp_path / "cache", IDENT)
    c.dir.mkdir(parents=True)
    (c.dir / f"{pc.file_sha256(f)}.json.gz").write_bytes(b"garbage")
    parse = CountingParser()
    assert pc.parse_with_cache(f, parse, c) == _doc("x.pdf") and parse.calls == 1
    assert c.get(pc.file_sha256(f), "x.pdf") == _doc("x.pdf")


def test_worker_parse_uses_the_configured_cache(tmp_path, monkeypatch):
    """The ingestion worker's parse step reads the cache when PARSE_CACHE_DIR is set."""
    from ragline.config import settings
    from ragline.ingestion import worker

    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF worker bytes")
    parse = CountingParser()
    monkeypatch.setattr(worker, "get_parser", lambda path: type("P", (), {"parse": staticmethod(parse)})())
    monkeypatch.setattr(settings, "parse_cache_dir", str(tmp_path / "cache"))
    worker._parse_document(str(f))
    worker._parse_document(str(f))
    assert parse.calls == 1
    # Cache off: back to parsing every time.
    monkeypatch.setattr(settings, "parse_cache_dir", "")
    worker._parse_document(str(f))
    assert parse.calls == 2


# --- scripts/preparse.py --------------------------------------------------------

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "preparse.py"
spec = importlib.util.spec_from_file_location("preparse_script", SCRIPT)
pp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pp)


def test_preparse_skips_cached_and_fills_the_rest(tmp_path, monkeypatch, capsys):
    """Cached files are skipped; the others are parsed into the cache (stub parse, in-process pool)."""
    from concurrent.futures import ThreadPoolExecutor

    root = tmp_path / "docs"
    root.mkdir()
    for name in ("a.pdf", "b.pdf", "c.txt"):
        (root / name).write_bytes(f"bytes of {name}".encode())
    cache_root = tmp_path / "cache"
    monkeypatch.setattr(pp, "parser_identity", lambda: IDENT)
    monkeypatch.setattr(pp, "ocr_engine", lambda: "5.3.4")
    monkeypatch.setattr(pp, "supported_extensions", lambda: [".pdf"])
    # Workers become threads and the parser a stub, so the test needs no PDFs and no processes.
    monkeypatch.setattr(pp, "ProcessPoolExecutor", ThreadPoolExecutor)
    parse = CountingParser()
    monkeypatch.setattr(pp, "get_parser", lambda path: type("P", (), {"parse": staticmethod(parse)})())
    monkeypatch.setattr(pp, "_quiet_logs", lambda: None)
    # a.pdf is cached already.
    pc.ParseCache(cache_root, IDENT).put(pc.file_sha256(root / "a.pdf"), _doc("a.pdf"))
    assert pp.main([str(root), "--cache-dir", str(cache_root), "--workers", "2"]) == 0
    assert parse.calls == 1                                        # only b.pdf
    assert pc.ParseCache(cache_root, IDENT).has(pc.file_sha256(root / "b.pdf"))
    assert "1 already cached, 1 to parse" in capsys.readouterr().out
    # Second run: nothing left to do.
    assert pp.main([str(root), "--cache-dir", str(cache_root)]) == 0 and parse.calls == 1


def test_preparse_needs_a_cache_dir(tmp_path, monkeypatch, capsys):
    """No --cache-dir and no PARSE_CACHE_DIR is an error, not a silent no-op."""
    from ragline.config import settings

    monkeypatch.setattr(settings, "parse_cache_dir", "")
    assert pp.main([str(tmp_path)]) == 1
    assert "no cache directory" in capsys.readouterr().out


def test_preparse_refuses_ocr_without_tesseract(tmp_path, monkeypatch, capsys):
    """OCR enabled but no engine: stop, unless --allow-no-ocr."""
    from ragline.config import settings

    monkeypatch.setattr(settings, "enable_ocr_fallback", True)
    monkeypatch.setattr(pp, "ocr_engine", lambda: "absent")
    assert pp.main([str(tmp_path), "--cache-dir", str(tmp_path / "c")]) == 1
    assert "Tesseract is not available" in capsys.readouterr().out
    # Allowed explicitly: an empty tree then just has nothing to do.
    monkeypatch.setattr(pp, "parser_identity", lambda: {**IDENT, "ocr_engine": "absent"})
    assert pp.main([str(tmp_path), "--cache-dir", str(tmp_path / "c"), "--allow-no-ocr"]) == 0
