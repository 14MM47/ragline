"""POST /documents/{id}/retry — re-ingest a document that errored.

Before this existed, a document that failed mid-ingest could not be recovered
or even removed from the UI (the delete control only rendered for 'ready'), so
the row had to be cleared by hand in SQL. Retry re-parses the stored copy,
which also means it picks up parser fixes shipped since the failure.

The guards matter as much as the happy path: retrying a healthy document would
duplicate its vectors, retrying an in-flight one would race the worker, and
retrying against a dead pod would just re-error the document and read as
"retry is broken".
"""

import pytest
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


class _Doc:
    """Minimal stand-in for the Document row the route reads."""

    def __init__(self, status: str):
        self.id = "doc-1"
        self.status = status
        self.batch_id = "batch-1"
        self.filename = "batch-1/manual.pdf"
        # Owned by the dev identity these auth-off tests run as — retry is
        # admin-or-owner gated (see test_destructive_authz.py).
        self.uploaded_by = "dev@localhost"


class _VectorStore:
    def __init__(self):
        self.deleted: list[str] = []

    async def delete_by_document_id(self, document_id: str) -> None:
        self.deleted.append(document_id)


@pytest.fixture
def client(monkeypatch):
    """App with just the documents router and every collaborator stubbed."""
    app = FastAPI()
    app.include_router(documents_route.router, prefix="/api")

    vector_store = _VectorStore()
    app.dependency_overrides[get_vector_store] = lambda: vector_store
    app.dependency_overrides[get_file_store] = lambda: object()
    app.dependency_overrides[get_embedder] = lambda: object()
    app.dependency_overrides[get_llm] = lambda: object()
    app.dependency_overrides[get_retrieval_pipeline] = lambda: object()

    state: dict = {"updates": [], "chunks_deleted": [], "spawned": [], "vector_store": vector_store}

    async def fake_update_document(doc_id: str, **kwargs):
        state["updates"].append((doc_id, kwargs))

    async def fake_delete_chunk_records(doc_id: str):
        state["chunks_deleted"].append(doc_id)

    def fake_spawn_background(coro):
        state["spawned"].append(coro)
        coro.close()  # never actually run the worker in a unit test
        return None

    monkeypatch.setattr(documents_route, "update_document", fake_update_document)
    monkeypatch.setattr(documents_route, "delete_chunk_records", fake_delete_chunk_records)
    monkeypatch.setattr(documents_route, "spawn_background", fake_spawn_background)
    monkeypatch.setattr(documents_route, "BatchWorker", lambda *a, **k: _StubWorker())

    with TestClient(app) as c:
        yield c, state


class _StubWorker:
    async def process_batch(self, batch_id: str):
        return None


def _patch_doc(monkeypatch, doc):
    async def fake_get_document(doc_id: str):
        return doc

    monkeypatch.setattr(documents_route, "get_document", fake_get_document)


def _patch_services(monkeypatch, **services):
    """Stub the health probe the route imports inside the function body."""
    from ragline.api.routes import health

    async def fake_probe():
        return {"llm": True, "embedder": True, "reranker": True, **services}

    monkeypatch.setattr(health, "probe_services", fake_probe)


def test_missing_document_404s(client, monkeypatch):
    c, _ = client
    _patch_doc(monkeypatch, None)
    assert c.post("/api/documents/doc-1/retry").status_code == 404


@pytest.mark.parametrize("status", ["ready", "processing", "pending", "skipped_duplicate"])
def test_non_error_document_409s(client, monkeypatch, status):
    """Only 'error' documents may be retried."""
    c, state = client
    _patch_doc(monkeypatch, _Doc(status))
    _patch_services(monkeypatch)

    res = c.post("/api/documents/doc-1/retry")

    assert res.status_code == 409
    assert status in res.json()["detail"]
    # Nothing may be cleared or queued for a document that was not retried.
    assert state["chunks_deleted"] == []
    assert state["spawned"] == []


def test_embedder_down_503s(client, monkeypatch):
    """A retry against a dead pod is refused, not burned."""
    c, state = client
    _patch_doc(monkeypatch, _Doc("error"))
    _patch_services(monkeypatch, embedder=False)

    res = c.post("/api/documents/doc-1/retry")

    assert res.status_code == 503
    assert state["updates"] == []
    assert state["spawned"] == []


def test_retry_clears_partial_state_and_requeues(client, monkeypatch):
    """Happy path: vectors + chunk rows cleared, status reset, worker queued."""
    c, state = client
    _patch_doc(monkeypatch, _Doc("error"))
    _patch_services(monkeypatch)

    res = c.post("/api/documents/doc-1/retry")

    assert res.status_code == 200
    assert res.json()["status"] == "retrying"
    # Partial output from the failed attempt is removed, or re-processing
    # would append a second copy of whatever it got through.
    assert state["vector_store"].deleted == ["doc-1"]
    assert state["chunks_deleted"] == ["doc-1"]
    # Reset to pending so process_batch picks it up; stage cleared for the UI.
    assert state["updates"] == [("doc-1", {"status": "pending", "stage": ""})]
    assert len(state["spawned"]) == 1
