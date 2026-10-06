"""scripts/build_corpus_index.py + scripts/fetch_corpus.py — the corpus index.

Loads both scripts as modules (neither imports ragline) and checks the pure
logic: URL cleaning, path splitting, the golden cross-reference, row
selection, the path-escape guard, and the fetch statuses that need no network.
A last test pins the committed manifest to the committed golden set, so a
question can never cite a document the index does not list.
"""

import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    """Import scripts/<name>.py as a module without touching sys.path."""
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bci = _load("build_corpus_index")
fc = _load("fetch_corpus")


# --- build_corpus_index ------------------------------------------------------

def test_clean_url_drops_placeholders_and_signatures():
    # The fetch log marks files that predate it with a word, not a URL.
    assert bci.clean_url("PRE-EXISTING") == ""
    assert bci.clean_url("") == ""
    # A per-download signature is stripped; the address itself survives.
    signed = "https://lib.example/public/abc/Doc.pdf?x-sign=AAA%2Bbbb"
    assert bci.clean_url(signed) == "https://lib.example/public/abc/Doc.pdf"


def test_clean_url_leaves_ordinary_urls_byte_identical():
    # Cache-busting and download flags are how the vendor serves the file —
    # they must come back untouched, including their original escaping.
    for url in (
        "https://files.example/doc%20name.pdf?v=3",
        "https://cache.example/attachments/1/manual.pdf?download=true",
        "https://plain.example/a.pdf",
    ):
        assert bci.clean_url(url) == url


def test_split_path_handles_shallow_files():
    assert bci.split_path("hmi/weintek/cmt-series/x.pdf") == ("hmi", "weintek", "cmt-series")
    assert bci.split_path("hmi/weintek/x.pdf") == ("hmi", "weintek", "")
    assert bci.split_path("x.pdf") == ("", "", "")


def test_golden_references_maps_sources_to_ids(tmp_path):
    golden = tmp_path / "g.json"
    golden.write_text(json.dumps([
        {"id": "A01", "expected_sources": ["hmi/a.pdf"]},
        {"id": "A02", "expected_sources": ["hmi/a.pdf", "hmi/b.pdf"]},
        {"expected_sources": ["hmi/c.pdf"]},  # no id (draft sets) — ignored
    ]))
    assert bci.golden_references([golden]) == {"hmi/a.pdf": ["A01", "A02"], "hmi/b.pdf": ["A02"]}


def test_read_fetch_log_cleans_urls_and_skips_bad_lines(tmp_path):
    log = tmp_path / "log.tsv"
    log.write_text(
        "hmi/a.pdf\tabc\t10\thttps://x.example/a.pdf?x-sign=s\n"
        "\n"
        "short\tline\n"
        "hmi/b.pdf\tdef\t20\tPRE-EXISTING\n"
    )
    rows = bci.read_fetch_log(log)
    assert rows["hmi/a.pdf"] == {"sha256": "abc", "size_bytes": 10, "source_url": "https://x.example/a.pdf"}
    assert rows["hmi/b.pdf"]["source_url"] == ""
    assert set(rows) == {"hmi/a.pdf", "hmi/b.pdf"}


def test_build_rows_rehashes_a_changed_pdf_with_the_same_size(tmp_path, monkeypatch):
    original = b"%PDF-original"
    changed = b"%PDF-modified"
    assert len(original) == len(changed)
    pdf = tmp_path / "hmi" / "vendor" / "manual.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(changed)
    old_digest = hashlib.sha256(original).hexdigest()
    fetch_log = {
        "hmi/vendor/manual.pdf": {
            "sha256": old_digest,
            "size_bytes": len(original),
            "source_url": "https://vendor.example/manual.pdf",
        },
    }
    monkeypatch.setattr(bci, "pdf_facts", lambda _path: (1, "Manual"))

    row, = bci.build_rows(tmp_path, fetch_log, {}, {"hmi/vendor/manual.pdf": ["A01"]})

    assert row["sha256"] == hashlib.sha256(changed).hexdigest()
    assert row["sha256"] != old_digest
    assert row["size_bytes"] == len(changed)
    assert row["source_url"] == fetch_log["hmi/vendor/manual.pdf"]["source_url"]
    assert row["golden_questions"] == "A01"


def test_render_index_lists_the_highlighted_category_in_full():
    rows = [
        {"path": "hmi/v/f/a.pdf", "category": "hmi", "vendor": "v", "product_family": "f", "title": "A | B",
         "pages": 2, "size_bytes": 1000, "sha256": "s", "source_url": "https://x.example/a.pdf",
         "golden_questions": "A01"},
        {"path": "plc/w/g/b.pdf", "category": "plc", "vendor": "w", "product_family": "g", "title": "",
         "pages": 5, "size_bytes": 2000, "sha256": "t", "source_url": "", "golden_questions": ""},
    ]
    text = bci.render_index(rows, "hmi")
    assert "`a.pdf`" in text and "A01" in text and "[link](https://x.example/a.pdf)" in text
    assert "A \\| B" in text, "a pipe in a PDF title must not break the table"
    # The other category appears as a breakdown, not file by file.
    assert "`b.pdf`" not in text and "**w** — g (1)" in text


# --- fetch_corpus ------------------------------------------------------------

ROWS = [
    {"path": "hmi/v/a.pdf", "category": "hmi", "golden_questions": "A01"},
    {"path": "hmi/v/b.pdf", "category": "hmi", "golden_questions": ""},
    {"path": "plc/w/c.pdf", "category": "plc", "golden_questions": ""},
]


def test_select_rows_filters_by_category_and_golden():
    assert len(fc.select_rows(ROWS, None, False)) == 3
    assert [r["path"] for r in fc.select_rows(ROWS, ["HMI"], False)] == ["hmi/v/a.pdf", "hmi/v/b.pdf"]
    assert [r["path"] for r in fc.select_rows(ROWS, None, True)] == ["hmi/v/a.pdf"]
    assert fc.select_rows(ROWS, ["vfd"], False) == []


def test_safe_target_refuses_paths_that_escape(tmp_path):
    assert fc.safe_target(tmp_path, "hmi/v/a.pdf") == (tmp_path / "hmi/v/a.pdf").resolve()
    for bad in ("../outside.pdf", "hmi/../../outside.pdf", "/etc/passwd"):
        with pytest.raises(ValueError):
            fc.safe_target(tmp_path, bad)


def test_fetch_row_statuses_without_network(tmp_path):
    body = b"%PDF-1.7 fake"
    digest = hashlib.sha256(body).hexdigest()
    target = tmp_path / "hmi/v/a.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(body)

    # Intact file: skipped, whether or not a URL is known.
    assert fc.fetch_row({"path": "hmi/v/a.pdf", "sha256": digest, "source_url": ""}, tmp_path, 1, False) == "present"
    # Same file, different recorded digest: reported, never overwritten.
    row = {"path": "hmi/v/a.pdf", "sha256": "0" * 64, "source_url": "https://unused.invalid/a.pdf"}
    assert fc.fetch_row(row, tmp_path, 1, False) == "differs"
    assert target.read_bytes() == body
    # Missing file: no URL -> no-url; URL + dry run -> would-fetch (nothing written).
    assert fc.fetch_row({"path": "hmi/v/b.pdf", "sha256": digest, "source_url": ""}, tmp_path, 1, False) == "no-url"
    row = {"path": "hmi/v/c.pdf", "sha256": digest, "source_url": "https://unused.invalid/c.pdf"}
    assert fc.fetch_row(row, tmp_path, 1, True) == "would-fetch"
    assert not (tmp_path / "hmi/v/c.pdf").exists()


def test_download_rejects_a_non_pdf_response(tmp_path, monkeypatch):
    class _Html:
        """Stands in for a 200 response that is really a 'document moved' page."""
        def __init__(self):
            self._chunks = [b"<html>moved</html>", b""]
        def read(self, _n):
            return self._chunks.pop(0)
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(fc.urllib.request, "urlopen", lambda *a, **k: _Html())
    target = tmp_path / "a.pdf"
    with pytest.raises(ValueError):
        fc.download("https://unused.invalid/a.pdf", target, 1)
    # Neither the real name nor the .part file is left behind.
    assert list(tmp_path.iterdir()) == []


# --- the committed index -----------------------------------------------------

def test_committed_manifest_covers_the_golden_set():
    with (REPO / "eval/corpus/manifest.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == bci.COLUMNS
    by_path = {row["path"]: row for row in rows}
    assert len(by_path) == len(rows), "duplicate path in manifest.csv"
    golden = json.loads((REPO / "eval/golden_set_hmi.json").read_text(encoding="utf-8"))
    for item in golden:
        for source in item.get("expected_sources", []):
            assert source in by_path, f"{item['id']} cites {source}, which the corpus index does not list"
            assert item["id"] in by_path[source]["golden_questions"].split()
    # Nothing in the public index may carry a signature or a local path.
    for row in rows:
        assert "x-sign" not in row["source_url"]
        assert row["source_url"] == "" or row["source_url"].startswith(("http://", "https://"))
        assert len(row["sha256"]) == 64
