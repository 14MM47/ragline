"""Document routes — single upload, listing, content serving, versions, delete.

Ported from raggles minus audit logging and access groups, plus the
`original_path` form field: the network location the file was uploaded from,
carried into citations. GET /{id}/content serves the managed copy inline —
the citation sidebar's "Open copy" link appends #page=N so the browser's PDF
viewer jumps straight to the cited page.
"""

import hashlib
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ragline.api.dependencies import (
    get_embedder,
    get_file_store,
    get_llm,
    get_retrieval_pipeline,
    get_vector_store,
)
from ragline.api.explorer import build_explorer, layout_for
from ragline.api.schemas import BatchUploadResponse, DocumentSchema, ExplorerResponse
from ragline.auth.dependencies import AuthedUser, get_current_user
from ragline.config import settings
from ragline.embeddings.base import BaseEmbedder
from ragline.ingestion.worker import BatchWorker, spawn_background
from ragline.llm.base import BaseLLM
from ragline.parsing.registry import supported_extensions
from ragline.storage.file_store import BaseFileStore
from ragline.storage.layout import clear_placement, list_folders, list_placements
from ragline.storage.metadata_db import (
    create_batch,
    create_document,
    delete_chunk_records,
    delete_document,
    get_batch_documents,
    get_document,
    get_version_history,
    update_document,
)
from ragline.vectorstore.base import BaseVectorStore

log = structlog.get_logger()
router = APIRouter(prefix="/documents", tags=["documents"])


def _require_admin_or_owner(user: AuthedUser, doc) -> None:
    """Destructive operations: admins, or the user who uploaded the document.

    The empty-string guard matters: crawled/legacy rows have uploaded_by=""
    and a token without a UPN claim yields user.upn="" — those must never
    match each other.
    """
    if user.is_admin:
        return
    if doc.uploaded_by and doc.uploaded_by == user.upn:
        return
    raise HTTPException(403, "Only the uploader or an admin can modify this document")


@router.post("/upload", response_model=BatchUploadResponse)
async def upload_document(
    file: UploadFile,
    # Optional provenance: full original network path of THIS file.
    original_path: str = Form(default=""),
    file_store: BaseFileStore = Depends(get_file_store),
    embedder: BaseEmbedder = Depends(get_embedder),
    vector_store: BaseVectorStore = Depends(get_vector_store),
    pipeline=Depends(get_retrieval_pipeline),
    llm: BaseLLM = Depends(get_llm),
    user: AuthedUser = Depends(get_current_user),
):
    """Upload one file; processed as a batch of 1 in the background."""
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    # Reject unsupported extensions up front.
    ext = Path(file.filename).suffix.lower()
    if ext not in supported_extensions():
        raise HTTPException(400, f"Unsupported file type: {ext}. Supported: {supported_extensions()}")

    # Read the bytes once; hash powers duplicate detection.
    data = await file.read()
    file_hash = hashlib.sha256(data).hexdigest()

    # Every upload is a batch — a single file is just a batch of 1.
    batch = await create_batch(total_files=1)

    # Store under "{batch_id}/{basename}"; that storage path IS
    # Document.filename (the worker resolves files by it).
    safe_name = Path(file.filename).name
    storage_path = f"{batch.id}/{safe_name}"
    await file_store.save(storage_path, data)

    await create_document(
        filename=storage_path,
        file_type=ext.lstrip("."),
        file_hash=file_hash,
        batch_id=batch.id,
        source_path=safe_name,
        # Provenance stored verbatim ("" when the uploader didn't supply it).
        original_path=original_path.strip(),
        uploaded_by=user.upn,
    )

    # Kick off ingestion without blocking the response.
    worker = BatchWorker(file_store, embedder, vector_store, pipeline, llm=llm)
    spawn_background(worker.process_batch(batch.id))

    return BatchUploadResponse(batch_id=batch.id, total_files=1)


@router.get("", response_model=list[DocumentSchema])
async def list_docs(user: AuthedUser = Depends(get_current_user)):
    """All documents, newest first — the Documents tab listing.

    original_path is per-user data (same ACL gate as citations): restricted
    documents stay listed, but WHERE they live on the network is blanked.
    The explorer coordinates (upload_root, folder_path, duplicate_of) come
    from the same pass — see api/explorer.py.
    """
    return (await build_explorer(user)).rows


@router.get("/explorer", response_model=ExplorerResponse)
async def explorer(user: AuthedUser = Depends(get_current_user)):
    """Documents + the shared layout in one call (the Documents tab's poll).

    One document scan and one ACL query serve both halves; calling
    /documents and /documents/layout separately did that work twice.
    """
    view = await build_explorer(user)
    folders, placements = await list_folders(), await list_placements()
    return ExplorerResponse(documents=view.rows, layout=layout_for(view, folders, placements))


@router.delete("/{document_id}")
async def delete_doc(
    document_id: str,
    vector_store: BaseVectorStore = Depends(get_vector_store),
    file_store: BaseFileStore = Depends(get_file_store),
    pipeline=Depends(get_retrieval_pipeline),
    user: AuthedUser = Depends(get_current_user),
):
    """Remove a document everywhere: vectors, stored file, DB rows, KG, BM25."""
    doc = await get_document(document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    _require_admin_or_owner(user, doc)

    # Order: vectors first (search stops returning it), then file, then rows.
    await vector_store.delete_by_document_id(document_id)
    await file_store.delete(doc.filename)
    # Explorer placement first: it references document.id, so it must go
    # before the row it points at (SQLite does not enforce the FK today, but
    # the order is right if that ever changes).
    await clear_placement(document_id)
    await delete_document(document_id)
    # BM25 index must forget the document's chunks too — unless the row never
    # produced any (a skipped duplicate): a full rebuild per deleted marker
    # row would make clearing 30 of them a minute-long affair for nothing.
    if doc.status != "skipped_duplicate":
        await pipeline.rebuild_bm25_index()

    # Knowledge-graph cleanup is best-effort — orphaned entities are harmless.
    try:
        from ragline.knowledge_graph.store import delete_entities_by_document

        await delete_entities_by_document(document_id)
    except Exception:
        log.warning("failed to clean up knowledge graph entities", document_id=document_id, exc_info=True)

    return {"status": "deleted", "document_id": document_id}


@router.post("/{document_id}/retry")
async def retry_doc(
    document_id: str,
    file_store: BaseFileStore = Depends(get_file_store),
    embedder: BaseEmbedder = Depends(get_embedder),
    vector_store: BaseVectorStore = Depends(get_vector_store),
    pipeline=Depends(get_retrieval_pipeline),
    llm: BaseLLM = Depends(get_llm),
    user: AuthedUser = Depends(get_current_user),
):
    """Re-ingest a document that previously errored.

    The uploaded copy is still in the file store, so this re-parses from disk —
    which means a retry also picks up any parser fixes shipped since the failed
    attempt. Only 'error' documents qualify: retrying a healthy one would
    duplicate its vectors, and retrying an in-flight one would race the worker.
    """
    from ragline.api.routes.health import probe_services
    from ragline.config import settings

    doc = await get_document(document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    _require_admin_or_owner(user, doc)
    if doc.status != "error":
        raise HTTPException(
            409, f"Only documents with status 'error' can be retried (this one is '{doc.status}')"
        )

    # Refuse rather than burn the attempt: re-processing against a dead embedder
    # just marks the document errored again, which reads as "retry is broken".
    services = await probe_services()
    if not services.get("embedder"):
        raise HTTPException(503, "Embedding service is unavailable — bring the pod up first")
    if settings.enable_knowledge_graph and not services.get("llm"):
        raise HTTPException(503, "LLM is unavailable and the knowledge graph is enabled")

    # Clear whatever the failed attempt managed to write, or re-processing
    # would append a second copy of everything it got through last time.
    await vector_store.delete_by_document_id(document_id)
    await delete_chunk_records(document_id)
    try:
        from ragline.knowledge_graph.store import delete_entities_by_document

        await delete_entities_by_document(document_id)
    except Exception:
        log.warning("failed to clean up knowledge graph entities", document_id=document_id, exc_info=True)

    # Back to the queue. process_batch only picks up 'pending' documents, so
    # the batch's already-ready siblings are left alone.
    await update_document(document_id, status="pending", stage="")

    worker = BatchWorker(file_store, embedder, vector_store, pipeline, llm=llm)
    spawn_background(worker.process_batch(doc.batch_id))

    log.info("document retry queued", document_id=document_id, batch_id=doc.batch_id)
    return {"status": "retrying", "document_id": document_id, "batch_id": doc.batch_id}


@router.get("/{document_id}/content")
async def get_document_content(
    document_id: str,
    file_store: BaseFileStore = Depends(get_file_store),
    user: AuthedUser = Depends(get_current_user),
):
    """Serve the managed copy inline — the citation "Open copy" target.

    THE ACL security boundary. The `accessible` flag on citation payloads is
    UX only; this check runs on every download regardless of what the UI
    showed, via the same accessible() the enrichment uses (they can never
    disagree). The browser interprets a #page=N fragment on this URL to open
    PDFs at the cited page; the server itself ignores fragments entirely.
    """
    doc = await get_document(document_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    if settings.auth_enabled:
        from ragline.acl.access import accessible
        from ragline.auth.graph import effective_groups
        from ragline.storage.acl_models import get_acls_by_document_ids

        acl = (await get_acls_by_document_ids([document_id])).get(document_id)
        groups = await effective_groups(user)
        if not accessible(user, acl, groups=groups):
            raise HTTPException(
                403,
                "Restricted by the source file's permissions — you don't have "
                "access to the original document on the network share.",
            )

    path = await file_store.get_path(doc.filename)
    if not path.exists():
        raise HTTPException(404, "File not found on disk")

    # Serve inline with the right media type so the browser opens (not
    # downloads) the document.
    media_types = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    media_type = media_types.get(doc.file_type, "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@router.post("/{document_id}/new-version", response_model=BatchUploadResponse)
async def upload_new_version(
    document_id: str,
    file: UploadFile,
    original_path: str = Form(default=""),
    file_store: BaseFileStore = Depends(get_file_store),
    embedder: BaseEmbedder = Depends(get_embedder),
    vector_store: BaseVectorStore = Depends(get_vector_store),
    pipeline=Depends(get_retrieval_pipeline),
    llm: BaseLLM = Depends(get_llm),
    user: AuthedUser = Depends(get_current_user),
):
    """Upload a new version of an existing document (old version is kept)."""
    old_doc = await get_document(document_id)
    if not old_doc:
        raise HTTPException(404, "Document not found")

    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in supported_extensions():
        raise HTTPException(400, f"Unsupported file type: {ext}")

    data = await file.read()
    file_hash = hashlib.sha256(data).hexdigest()

    # New version = new batch-of-1 with its own storage path.
    batch = await create_batch(total_files=1)
    safe_name = Path(file.filename).name
    storage_path = f"{batch.id}/{safe_name}"
    await file_store.save(storage_path, data)

    new_version = (old_doc.version or 1) + 1
    await create_document(
        filename=storage_path,
        file_type=ext.lstrip("."),
        file_hash=file_hash,
        batch_id=batch.id,
        # Same source_path as the old doc — that's the version-chain key.
        source_path=old_doc.source_path or file.filename,
        # New provenance if given, else inherit the old version's.
        original_path=original_path.strip() or old_doc.original_path,
        # Attributed to whoever uploaded THIS version, not the original's owner.
        uploaded_by=user.upn,
    )

    # Stamp the version chain fields on the just-created row.
    new_docs = await get_batch_documents(batch.id)
    if new_docs:
        await update_document(
            new_docs[0].id,
            version=new_version,
            previous_version_id=document_id,
        )

    worker = BatchWorker(file_store, embedder, vector_store, pipeline, llm=llm)
    spawn_background(worker.process_batch(batch.id))

    return BatchUploadResponse(batch_id=batch.id, total_files=1)


@router.get("/{document_id}/versions")
async def document_versions(document_id: str, user: AuthedUser = Depends(get_current_user)):
    """Full version history for a document (newest first).

    original_path gated per user, per VERSION — each version row has its own
    ACL crawl (old versions may live at a different network location).
    """
    from ragline.acl.access import accessible_document_ids

    versions = await get_version_history(document_id)
    if not versions:
        raise HTTPException(404, "Document not found")

    allowed = await accessible_document_ids(user, [d.id for d in versions])
    return [
        {
            "id": d.id,
            "version": d.version,
            "filename": d.source_path if d.source_path else d.filename,
            "upload_date": d.upload_date.isoformat(),
            "status": d.status,
            "page_count": d.page_count,
            "chunk_count": d.chunk_count,
            "previous_version_id": d.previous_version_id,
            "original_path": d.original_path if d.id in allowed else "",
        }
        for d in versions
    ]
