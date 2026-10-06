"""End-of-chain ACL gating — the /content 403 and citation enrichment.

The 403 test is the one that matters most: it proves a hand-crafted URL is
refused server-side regardless of anything the UI displayed. The enrichment
tests prove the payload never leaks a restricted file's network path.
"""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ragline.auth.graph as graph_module
import ragline.storage.acl_models as acl_models
from ragline.api import explorer as explorer_module
from ragline.api.dependencies import (
    get_embedder,
    get_file_store,
    get_llm,
    get_retrieval_pipeline,
    get_vector_store,
)
from ragline.api.routes import chat as chat_route
from ragline.api.routes import documents as documents_route
from ragline.auth.dependencies import AuthedUser, get_current_user
from ragline.config import settings
from ragline.storage.acl_models import DocumentAcl

OID_USER = "11111111-1111-1111-1111-111111111111"
OID_GROUP = "22222222-2222-2222-2222-222222222222"


def _fresh_acl(document_id: str, principals: str = "[]", allow_all: bool = False) -> DocumentAcl:
    now = datetime.now(timezone.utc)
    return DocumentAcl(
        document_id=document_id,
        crawl_status="ok",
        principals_json=principals,
        allow_all_authenticated=allow_all,
        last_ok_at=now,
        crawled_at=now,
    )


class _Doc:
    def __init__(self, doc_id: str):
        self.id = doc_id
        self.status = "ready"
        self.filename = f"batch/{doc_id}.pdf"
        self.file_type = "pdf"
        self.original_path = r"\\fs1\share\secret.pdf"


@pytest.fixture
def content_client(monkeypatch):
    """Documents router with auth ON and a restricted ACL row."""
    settings.auth_enabled = True

    app = FastAPI()
    app.include_router(documents_route.router, prefix="/api")
    for dep in (get_vector_store, get_file_store, get_embedder, get_llm, get_retrieval_pipeline):
        app.dependency_overrides[dep] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: AuthedUser(oid=OID_USER, groups=[])

    async def fake_get_document(doc_id):
        return _Doc(doc_id)

    monkeypatch.setattr(documents_route, "get_document", fake_get_document)

    async def fake_effective_groups(user):
        return user.groups

    monkeypatch.setattr(graph_module, "effective_groups", fake_effective_groups)
    return app, monkeypatch


def _patch_acls(monkeypatch, acls: dict):
    async def fake_get_acls(ids):
        return {k: v for k, v in acls.items() if k in ids}

    monkeypatch.setattr(acl_models, "get_acls_by_document_ids", fake_get_acls)


def test_content_403_when_not_permitted(content_client):
    app, monkeypatch = content_client
    _patch_acls(monkeypatch, {"doc-1": _fresh_acl("doc-1", principals=f'["{OID_GROUP}"]')})
    res = TestClient(app).get("/api/documents/doc-1/content")
    assert res.status_code == 403
    assert "permissions" in res.json()["detail"]


def test_content_403_when_no_acl_row(content_client):
    app, monkeypatch = content_client
    _patch_acls(monkeypatch, {})
    assert TestClient(app).get("/api/documents/doc-1/content").status_code == 403


def test_content_allowed_reaches_file_serving(content_client):
    app, monkeypatch = content_client
    _patch_acls(monkeypatch, {"doc-1": _fresh_acl("doc-1", allow_all=True)})

    class _Store:
        async def get_path(self, filename):
            from pathlib import Path

            return Path("/nonexistent/for-this-test.pdf")

    app.dependency_overrides[get_file_store] = lambda: _Store()
    # Past the ACL gate, the missing file yields the endpoint's own 404 —
    # proving the 403 above came from the ACL check, not from file serving.
    assert TestClient(app).get("/api/documents/doc-1/content").status_code == 404


# --- enrichment --------------------------------------------------------------


class _MetaDoc:
    def __init__(self, doc_id, path):
        self.id = doc_id
        self.original_path = path


@pytest.mark.asyncio
async def test_enrichment_sets_flag_and_suppresses_restricted_path(monkeypatch):
    settings.auth_enabled = True

    async def fake_get_documents_by_ids(ids):
        return {
            "doc-ok": _MetaDoc("doc-ok", r"\\fs1\share\open.pdf"),
            "doc-no": _MetaDoc("doc-no", r"\\fs1\share\secret.pdf"),
        }

    monkeypatch.setattr(chat_route, "get_documents_by_ids", fake_get_documents_by_ids)
    _patch_acls(
        monkeypatch,
        {"doc-ok": _fresh_acl("doc-ok", allow_all=True), "doc-no": _fresh_acl("doc-no")},
    )

    async def fake_effective_groups(user):
        return user.groups

    monkeypatch.setattr(graph_module, "effective_groups", fake_effective_groups)

    sources = [
        {"document_id": "doc-ok", "source_file": "open.pdf"},
        {"document_id": "doc-no", "source_file": "secret.pdf"},
    ]
    user = AuthedUser(oid=OID_USER, groups=[])
    await chat_route.enrich_sources_with_original_paths(sources, user=user)

    assert sources[0]["accessible"] is True
    assert sources[0]["original_path"] == r"\\fs1\share\open.pdf"
    # Restricted: flag false AND the path does not leak.
    assert sources[1]["accessible"] is False
    assert sources[1]["original_path"] == ""


# --- listing endpoints (F2): original_path must be per-user everywhere ------


class _ListDoc:
    """Enough Document surface for the listing serializers."""

    def __init__(self, doc_id, path):
        self.id = doc_id
        self.source_path = f"{doc_id}.pdf"
        self.filename = f"batch/{doc_id}.pdf"
        self.file_type = "pdf"
        self.upload_date = datetime.now(timezone.utc)
        self.page_count = 1
        self.chunk_count = 1
        self.status = "ready"
        self.stage = ""
        self.uploaded_by = "someone@corp"
        self.original_path = path
        self.version = 1
        self.previous_version_id = None
        self.batch_id = None
        self.file_hash = ""


_TWO_DOCS = [
    _ListDoc("doc-ok", r"\\fs1\share\open.pdf"),
    _ListDoc("doc-no", r"\\fs1\share\secret.pdf"),
]

def _patch_mixed_acls(monkeypatch):
    """doc-ok gets an allow-all row; doc-no has no ACL row at all (fail closed)."""
    _patch_acls(monkeypatch, {"doc-ok": _fresh_acl("doc-ok", allow_all=True)})


def test_document_listing_blanks_restricted_paths(content_client, monkeypatch):
    app, _ = content_client
    _patch_mixed_acls(monkeypatch)

    async def fake_list_documents():
        return _TWO_DOCS

    monkeypatch.setattr(explorer_module, "list_documents", fake_list_documents)
    body = TestClient(app).get("/api/documents").json()
    by_id = {d["id"]: d for d in body}
    # Both documents stay listed — only WHERE the restricted one lives is hidden.
    assert by_id["doc-ok"]["original_path"] == r"\\fs1\share\open.pdf"
    assert by_id["doc-no"]["original_path"] == ""


def test_version_history_blanks_restricted_paths(content_client, monkeypatch):
    app, _ = content_client
    _patch_mixed_acls(monkeypatch)

    async def fake_get_version_history(doc_id):
        return _TWO_DOCS

    monkeypatch.setattr(documents_route, "get_version_history", fake_get_version_history)
    body = TestClient(app).get("/api/documents/doc-ok/versions").json()
    by_id = {d["id"]: d for d in body}
    assert by_id["doc-ok"]["original_path"] == r"\\fs1\share\open.pdf"
    assert by_id["doc-no"]["original_path"] == ""


def test_batch_status_blanks_restricted_paths(monkeypatch):
    settings.auth_enabled = True
    from ragline.api.routes import batches as batches_route

    app = FastAPI()
    app.include_router(batches_route.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: AuthedUser(oid=OID_USER, groups=[])
    _patch_mixed_acls(monkeypatch)

    async def fake_effective_groups(user):
        return user.groups

    monkeypatch.setattr(graph_module, "effective_groups", fake_effective_groups)

    class _Batch:
        id = "batch-1"
        created_at = datetime.now(timezone.utc)
        total_files = 2
        completed_files = 2
        failed_files = 0
        skipped_files = 0
        status = "completed"

    async def fake_get_batch(batch_id):
        return _Batch()

    async def fake_get_batch_documents(batch_id):
        return _TWO_DOCS

    async def fake_count_batch_stages(batch_id):
        return {}

    monkeypatch.setattr(batches_route, "get_batch", fake_get_batch)
    monkeypatch.setattr(batches_route, "get_batch_documents", fake_get_batch_documents)
    monkeypatch.setattr(batches_route, "count_batch_stages", fake_count_batch_stages)

    body = TestClient(app).get("/api/batches/batch-1").json()
    by_id = {d["id"]: d for d in body["documents"]}
    assert by_id["doc-ok"]["original_path"] == r"\\fs1\share\open.pdf"
    assert by_id["doc-no"]["original_path"] == ""


@pytest.mark.asyncio
async def test_enrichment_auth_off_everything_accessible(monkeypatch):
    settings.auth_enabled = False

    async def fake_get_documents_by_ids(ids):
        return {"doc-1": _MetaDoc("doc-1", r"\\fs1\share\a.pdf")}

    monkeypatch.setattr(chat_route, "get_documents_by_ids", fake_get_documents_by_ids)
    sources = [{"document_id": "doc-1", "source_file": "a.pdf"}]
    await chat_route.enrich_sources_with_original_paths(sources, user=None)
    assert sources[0] == {
        "document_id": "doc-1",
        "source_file": "a.pdf",
        "original_path": r"\\fs1\share\a.pdf",
        "accessible": True,
    }


def test_document_listing_explorer_roots(content_client, monkeypatch):
    """Explorer root = network folder when visible, batch label when hidden."""
    app, _ = content_client
    _patch_mixed_acls(monkeypatch)
    stamp = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)
    docs = [_ListDoc("doc-ok", r"\\fs1\share\open.pdf"), _ListDoc("doc-no", r"\\fs1\share\secret.pdf")]
    for d in docs:
        d.batch_id = "a1b2c3d4-ffff-4000-8000-000000000000"
        d.upload_date = stamp
    # A nested upload-relative path drives folder_path.
    docs[0].source_path = "plc/siemens/doc-ok.pdf"
    docs[0].original_path = r"\\fs1\share\plc\siemens\doc-ok.pdf"

    async def fake_list_documents():
        return docs

    monkeypatch.setattr(explorer_module, "list_documents", fake_list_documents)
    body = TestClient(app).get("/api/documents").json()
    by_id = {d["id"]: d for d in body}
    # Visible provenance -> the real share is the root, folders from source_path.
    assert by_id["doc-ok"]["upload_root"] == r"\\fs1\share"
    assert by_id["doc-ok"]["folder_path"] == "plc/siemens"
    # Hidden provenance -> batch label root; the share name never leaks.
    assert by_id["doc-no"]["upload_root"] == "Upload 2026-09-12 · a1b2c3d4"
    assert by_id["doc-no"]["folder_path"] == ""


def test_document_listing_links_skipped_duplicates(content_client, monkeypatch):
    """A skipped_duplicate row names the ready document with the same bytes."""
    app, _ = content_client
    _patch_mixed_acls(monkeypatch)
    ready = _ListDoc("doc-ok", "")
    ready.file_hash = "abc"
    skipped = _ListDoc("doc-dup", "")
    skipped.file_hash = "abc"
    skipped.status = "skipped_duplicate"
    orphan = _ListDoc("doc-orphan", "")
    orphan.file_hash = "zzz"
    orphan.status = "skipped_duplicate"

    async def fake_list_documents():
        return [ready, skipped, orphan]

    monkeypatch.setattr(explorer_module, "list_documents", fake_list_documents)
    by_id = {d["id"]: d for d in TestClient(app).get("/api/documents").json()}
    assert by_id["doc-dup"]["duplicate_of"] == "doc-ok"
    # Ready rows never carry it; a skipped row whose twin is gone has "".
    assert by_id["doc-ok"]["duplicate_of"] == ""
    assert by_id["doc-orphan"]["duplicate_of"] == ""


def test_explorer_endpoint_combines_documents_and_layout(content_client, monkeypatch):
    """One call returns the caller's rows and the layout cut to their roots."""

    app, _ = content_client
    _patch_mixed_acls(monkeypatch)

    class _Folder:
        root, folder_path, created_by = r"\\fs1\share", "misc", "someone"

    async def fake_list_documents():
        return _TWO_DOCS

    async def fake_folders():
        return [_Folder()]

    async def fake_placements():
        return []

    monkeypatch.setattr(explorer_module, "list_documents", fake_list_documents)
    monkeypatch.setattr(documents_route, "list_folders", fake_folders)
    monkeypatch.setattr(documents_route, "list_placements", fake_placements)
    body = TestClient(app).get("/api/documents/explorer").json()
    assert {d["id"] for d in body["documents"]} == {"doc-ok", "doc-no"}
    # doc-ok is visible at the share, so the share-rooted folder is served.
    assert body["layout"]["folders"][0]["folder_path"] == "misc"
    assert body["layout"]["placements"] == []
