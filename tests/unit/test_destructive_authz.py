"""Destructive document routes — admin-or-owner authorization.

delete/retry were reachable by ANY authenticated user, including one the ACL
layer denies READ on the document — an authenticated user could destroy a
document they can't open. These tests prove the 403 fires for strangers,
that owner and admin proceed, that the empty-string identities never match
each other, and that a new version is attributed to its actual uploader.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ragline.api.dependencies import (
    get_embedder,
    get_file_store,
    get_llm,
    get_retrieval_pipeline,
    get_vector_store,
)
from ragline.api.routes import documents as documents_route
from ragline.auth.dependencies import AuthedUser, get_current_user
from ragline.config import settings

ADMIN_GROUP = "33333333-3333-3333-3333-333333333333"
OWNER_UPN = "owner@corp.example"


class _Doc:
    def __init__(self, uploaded_by=OWNER_UPN, status="error"):
        self.id = "doc-1"
        self.status = status
        self.filename = "batch-1/doc-1.pdf"
        self.file_type = "pdf"
        self.batch_id = "batch-1"
        self.uploaded_by = uploaded_by
        self.source_path = "doc-1.pdf"
        self.original_path = ""
        self.version = 1


class _FakeVectorStore:
    async def delete_by_document_id(self, doc_id):
        return None


class _FakeFileStore:
    async def delete(self, path):
        return None

    async def save(self, path, data):
        return None


class _FakePipeline:
    rebuilds = 0

    async def rebuild_bm25_index(self):
        _FakePipeline.rebuilds += 1
        return None


def _client(monkeypatch, user: AuthedUser, doc: _Doc) -> TestClient:
    app = FastAPI()
    app.include_router(documents_route.router, prefix="/api")
    app.dependency_overrides[get_vector_store] = lambda: _FakeVectorStore()
    app.dependency_overrides[get_file_store] = lambda: _FakeFileStore()
    app.dependency_overrides[get_retrieval_pipeline] = lambda: _FakePipeline()
    for dep in (get_embedder, get_llm):
        app.dependency_overrides[dep] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: user

    async def fake_get_document(doc_id):
        return doc

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(documents_route, "get_document", fake_get_document)
    monkeypatch.setattr(documents_route, "delete_document", _noop)
    monkeypatch.setattr(documents_route, "delete_chunk_records", _noop)
    monkeypatch.setattr(documents_route, "update_document", _noop)
    monkeypatch.setattr(documents_route, "clear_placement", _noop)
    # Fake worker's process_batch returns None (not a coroutine), so the
    # spawn_background noop leaves nothing un-awaited.
    monkeypatch.setattr(documents_route, "spawn_background", lambda coro: None)
    fake_worker = type("W", (), {"process_batch": lambda self, b: None})
    monkeypatch.setattr(documents_route, "BatchWorker", lambda *a, **k: fake_worker())
    return TestClient(app)


def test_delete_by_stranger_is_403(monkeypatch):
    stranger = AuthedUser(oid="oid-s", upn="stranger@corp.example")
    client = _client(monkeypatch, stranger, _Doc())
    resp = client.delete("/api/documents/doc-1")
    assert resp.status_code == 403


def test_delete_by_owner_succeeds(monkeypatch):
    owner = AuthedUser(oid="oid-o", upn=OWNER_UPN)
    client = _client(monkeypatch, owner, _Doc())
    resp = client.delete("/api/documents/doc-1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


def test_delete_by_admin_succeeds(monkeypatch):
    monkeypatch.setattr(settings, "entra_admin_group_id", ADMIN_GROUP)
    admin = AuthedUser(oid="oid-a", upn="admin@corp.example", groups=[ADMIN_GROUP])
    client = _client(monkeypatch, admin, _Doc())
    resp = client.delete("/api/documents/doc-1")
    assert resp.status_code == 200


def test_empty_uploaded_by_never_matches_empty_upn(monkeypatch):
    # Crawled/legacy rows have uploaded_by=""; a token without a UPN claim
    # yields upn="". "" == "" must NOT grant ownership.
    no_upn_user = AuthedUser(oid="oid-x", upn="")
    client = _client(monkeypatch, no_upn_user, _Doc(uploaded_by=""))
    resp = client.delete("/api/documents/doc-1")
    assert resp.status_code == 403


def test_retry_by_stranger_is_403(monkeypatch):
    stranger = AuthedUser(oid="oid-s", upn="stranger@corp.example")
    client = _client(monkeypatch, stranger, _Doc(status="error"))
    resp = client.post("/api/documents/doc-1/retry")
    assert resp.status_code == 403


def test_new_version_attributed_to_current_user(monkeypatch):
    captured = {}

    async def fake_create_batch(total_files):
        return type("B", (), {"id": "batch-2"})()

    async def fake_create_document(**kwargs):
        captured.update(kwargs)

    async def fake_get_batch_documents(batch_id):
        return []

    monkeypatch.setattr(documents_route, "create_batch", fake_create_batch)
    monkeypatch.setattr(documents_route, "create_document", fake_create_document)
    monkeypatch.setattr(documents_route, "get_batch_documents", fake_get_batch_documents)

    editor = AuthedUser(oid="oid-e", upn="editor@corp.example")
    client = _client(monkeypatch, editor, _Doc(uploaded_by=OWNER_UPN))
    resp = client.post(
        "/api/documents/doc-1/new-version",
        files={"file": ("doc-1.pdf", b"%PDF-1.4 new bytes")},
    )
    assert resp.status_code == 200
    # Attributed to the ACTUAL uploader of this version, not the original's owner.
    assert captured["uploaded_by"] == "editor@corp.example"


def test_delete_skipped_duplicate_skips_bm25_rebuild(monkeypatch):
    """A skipped_duplicate row has no chunks, so its delete must not rebuild BM25."""
    owner = AuthedUser(oid="oid-o", upn=OWNER_UPN)
    _FakePipeline.rebuilds = 0
    client = _client(monkeypatch, owner, _Doc(status="skipped_duplicate"))
    assert client.delete("/api/documents/doc-1").status_code == 200
    assert _FakePipeline.rebuilds == 0
    # A ready row still rebuilds.
    client = _client(monkeypatch, owner, _Doc(status="ready"))
    assert client.delete("/api/documents/doc-1").status_code == 200
    assert _FakePipeline.rebuilds == 1
