"""Server-folder ingest allowlist tests — the security boundary of
/batches/ingest-path.

The endpoint reads server-local files by client-supplied path, so everything
rides on _resolve_ingest_dir: feature off by default, strict containment in
INGEST_ROOTS, symlinks and '..' resolved BEFORE the containment check.
"""

import pytest
from fastapi import HTTPException

from ragline.api.routes.batches import _resolve_ingest_dir
from ragline.config import settings


def _set_roots(monkeypatch, value: str) -> None:
    """Point the module-singleton settings at a test allowlist."""
    monkeypatch.setattr(settings, "ingest_roots", value)


def test_disabled_by_default(monkeypatch, tmp_path):
    """Empty INGEST_ROOTS (the shipped default) refuses every request."""
    _set_roots(monkeypatch, "")
    with pytest.raises(HTTPException) as exc:
        _resolve_ingest_dir(str(tmp_path))
    assert exc.value.status_code == 400
    assert "disabled" in exc.value.detail


def test_path_inside_root_accepted(monkeypatch, tmp_path):
    """A directory inside an allowlisted root resolves to itself."""
    corpus = tmp_path / "corpus" / "vfd"
    corpus.mkdir(parents=True)
    _set_roots(monkeypatch, str(tmp_path / "corpus"))
    assert _resolve_ingest_dir(str(corpus)) == corpus


def test_root_itself_accepted(monkeypatch, tmp_path):
    """The allowlisted root is a valid target (ingest the whole corpus)."""
    _set_roots(monkeypatch, str(tmp_path))
    assert _resolve_ingest_dir(str(tmp_path)) == tmp_path


def test_path_outside_root_rejected(monkeypatch, tmp_path):
    """A sibling directory outside every root is a 403."""
    inside = tmp_path / "allowed"
    outside = tmp_path / "forbidden"
    inside.mkdir()
    outside.mkdir()
    _set_roots(monkeypatch, str(inside))
    with pytest.raises(HTTPException) as exc:
        _resolve_ingest_dir(str(outside))
    assert exc.value.status_code == 403


def test_dotdot_traversal_rejected(monkeypatch, tmp_path):
    """'..' segments are resolved before containment — escape is a 403."""
    inside = tmp_path / "allowed"
    (tmp_path / "secret").mkdir()
    inside.mkdir()
    _set_roots(monkeypatch, str(inside))
    with pytest.raises(HTTPException) as exc:
        _resolve_ingest_dir(str(inside / ".." / "secret"))
    assert exc.value.status_code == 403


def test_symlink_escape_rejected(monkeypatch, tmp_path):
    """A symlink inside a root pointing outside it must not pass."""
    inside = tmp_path / "allowed"
    outside = tmp_path / "elsewhere"
    inside.mkdir()
    outside.mkdir()
    # The link lives INSIDE the allowlisted root but resolves OUTSIDE it.
    (inside / "link").symlink_to(outside)
    _set_roots(monkeypatch, str(inside))
    with pytest.raises(HTTPException) as exc:
        _resolve_ingest_dir(str(inside / "link"))
    assert exc.value.status_code == 403


def test_file_not_directory_rejected(monkeypatch, tmp_path):
    """A file path (even allowlisted) is a 400 — the endpoint takes folders."""
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4")
    _set_roots(monkeypatch, str(tmp_path))
    with pytest.raises(HTTPException) as exc:
        _resolve_ingest_dir(str(f))
    assert exc.value.status_code == 400


def test_multiple_roots_parsed(monkeypatch, tmp_path):
    """';'-separated roots all count, with blanks/whitespace ignored."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _set_roots(monkeypatch, f"{a}; {b};;")
    assert settings.ingest_roots_list == [str(a), str(b)]
    assert _resolve_ingest_dir(str(b)) == b
