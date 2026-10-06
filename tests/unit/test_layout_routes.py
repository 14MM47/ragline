"""Explorer layout routes — per-user root visibility and the write paths.

The layout is shared, but a root that names a network share is served only
to users the ACL lets see a document at that share (the listing's rule for
original_path). Typed roots that no document derives from go to everyone.
"""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ragline.acl.access as access_module
from ragline.api import explorer as explorer_module
from ragline.api.routes import layout as layout_route
from ragline.auth.dependencies import AuthedUser, get_current_user
from ragline.storage import layout as layout_store
from ragline.storage.layout import LayoutError

SHARE = r"\\fs1\share"
BATCH = "a1b2c3d4-0000-4000-8000-000000000000"


class _Doc:
    """Enough Document surface for the explorer row builder."""

    def __init__(self, doc_id, original_path):
        self.id = doc_id
        self.source_path = f"{doc_id}.pdf"
        self.filename = f"batch/{doc_id}.pdf"
        self.original_path = original_path
        self.batch_id = BATCH
        self.upload_date = datetime(2026, 9, 12, tzinfo=timezone.utc)
        self.file_type = "pdf"
        self.file_hash = ""
        self.page_count = self.chunk_count = 1
        self.status = "ready"
        self.stage = self.uploaded_by = ""
        self.version = 1


class _Row:
    """Enough of a folder/placement row for the serializers."""

    def __init__(self, root, folder_path, **extra):
        self.root = root
        self.folder_path = folder_path
        self.created_by = extra.get("created_by", "")
        self.document_id = extra.get("document_id", "")


@pytest.fixture
def client(monkeypatch):
    """App with the layout router; `state` holds the fakes each test tunes."""
    state = {
        "user": AuthedUser(oid="u-ok", upn="ok@corp"),
        "allowed": {"doc-1"},
        "folders": [],
        "placements": [],
    }
    app = FastAPI()
    app.include_router(layout_route.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: state["user"]

    async def fake_list_documents():
        return [_Doc("doc-1", SHARE + r"\doc-1.pdf")]

    async def fake_accessible(user, ids):
        return set(state["allowed"])

    async def fake_list_folders():
        return state["folders"]

    async def fake_list_placements():
        return state["placements"]

    monkeypatch.setattr(explorer_module, "list_documents", fake_list_documents)
    monkeypatch.setattr(access_module, "accessible_document_ids", fake_accessible)
    monkeypatch.setattr(layout_store, "list_folders", fake_list_folders)
    monkeypatch.setattr(layout_store, "list_placements", fake_list_placements)
    return TestClient(app), state


def test_share_root_served_only_when_visible(client):
    tc, state = client
    state["folders"] = [_Row(SHARE, "misc"), _Row("Projects", "site-b")]
    state["placements"] = [_Row(SHARE, "misc", document_id="doc-9"), _Row("Projects", "", document_id="doc-8")]

    # This user can see doc-1 at the share -> both roots served.
    body = tc.get("/api/documents/layout").json()
    assert {f["root"] for f in body["folders"]} == {SHARE, "Projects"}
    assert {p["document_id"] for p in body["placements"]} == {"doc-9", "doc-8"}

    # Nothing accessible -> the share root disappears; the typed root stays.
    state["allowed"] = set()
    body = tc.get("/api/documents/layout").json()
    assert {f["root"] for f in body["folders"]} == {"Projects"}
    assert {p["document_id"] for p in body["placements"]} == {"doc-8"}


def test_batch_label_root_is_served_to_the_user_who_sees_it(client):
    tc, state = client
    # The hidden-provenance viewer's root for doc-1's batch.
    state["folders"] = [_Row("Upload 2026-09-12 · a1b2c3d4", "")]
    state["allowed"] = set()
    assert len(tc.get("/api/documents/layout").json()["folders"]) == 1
    # A viewer who sees the share does not get the batch-label root.
    state["allowed"] = {"doc-1"}
    assert tc.get("/api/documents/layout").json()["folders"] == []


def test_create_folder_validates(client, monkeypatch):
    tc, _ = client
    captured = {}

    async def fake_create(root, folder_path, created_by):
        captured.update(root=root, folder_path=folder_path, created_by=created_by)
        return _Row(root, folder_path, created_by=created_by)

    monkeypatch.setattr(layout_store, "create_folder", fake_create)
    resp = tc.post("/api/documents/layout/folders", json={"root": "Projects", "folder_path": "a/b"})
    assert resp.status_code == 201
    assert captured == {"root": "Projects", "folder_path": "a/b", "created_by": "ok@corp"}

    async def bad_create(root, folder_path, created_by):
        raise LayoutError("root must not be blank")

    monkeypatch.setattr(layout_store, "create_folder", bad_create)
    assert tc.post("/api/documents/layout/folders", json={"root": " "}).status_code == 400


def test_delete_folder_status_codes(client, monkeypatch):
    tc, _ = client

    async def missing(root, folder_path):
        return False

    async def occupied(root, folder_path):
        raise LayoutError("folder still contains moved documents")

    async def ok(root, folder_path):
        return True

    body = {"root": "Projects", "folder_path": "a"}
    monkeypatch.setattr(layout_store, "delete_folder", missing)
    assert tc.request("DELETE", "/api/documents/layout/folders", json=body).status_code == 404
    monkeypatch.setattr(layout_store, "delete_folder", occupied)
    assert tc.request("DELETE", "/api/documents/layout/folders", json=body).status_code == 409
    monkeypatch.setattr(layout_store, "delete_folder", ok)
    assert tc.request("DELETE", "/api/documents/layout/folders", json=body).status_code == 200


def test_move_requires_existing_document(client, monkeypatch):
    tc, _ = client
    moved = {}

    async def fake_get_document(doc_id):
        return object() if doc_id == "doc-1" else None

    async def fake_set(document_id, root, folder_path, moved_by):
        moved.update(document_id=document_id, root=root, folder_path=folder_path, moved_by=moved_by)
        return _Row(root, folder_path, document_id=document_id)

    async def fake_clear(document_id):
        return True

    monkeypatch.setattr(layout_route, "get_document", fake_get_document)
    monkeypatch.setattr(layout_store, "set_placement", fake_set)
    monkeypatch.setattr(layout_store, "clear_placement", fake_clear)
    body = {"root": "Projects", "folder_path": "x"}
    assert tc.put("/api/documents/layout/placements/nope", json=body).status_code == 404
    resp = tc.put("/api/documents/layout/placements/doc-1", json=body)
    assert resp.status_code == 200
    assert moved["document_id"] == "doc-1" and moved["moved_by"] == "ok@corp"
    assert tc.delete("/api/documents/layout/placements/doc-1").json() == {"status": "cleared", "removed": True}


def test_folder_ref_length_caps(client):
    """Oversized root/path bodies are refused at the schema, before storage."""
    tc, _ = client
    assert tc.post("/api/documents/layout/folders", json={"root": "x" * 513}).status_code == 422
    assert tc.post("/api/documents/layout/folders", json={"root": "ok", "folder_path": "y" * 1025}).status_code == 422
