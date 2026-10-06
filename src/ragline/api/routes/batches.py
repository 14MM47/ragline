"""Batch routes — multi-file / ZIP upload and batch progress polling.

Ported from raggles plus the `original_base_path` form field: when supplied,
every file's original network location is derived as
    original_path = join(original_base_path, relative_path_within_upload)
using the UNC-aware join in storage/paths.py — this is what citations later
display as "where this document really lives".
"""

import hashlib
import io
import zipfile
from pathlib import Path, PurePosixPath

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ragline.api.dependencies import (
    get_embedder,
    get_file_store,
    get_llm,
    get_retrieval_pipeline,
    get_vector_store,
)
from ragline.api.schemas import (
    BatchDocumentSchema,
    BatchListItem,
    BatchStatusResponse,
    BatchUploadResponse,
    IngestPathRequest,
)
from ragline.auth.dependencies import AuthedUser, get_current_user
from ragline.config import settings
from ragline.embeddings.base import BaseEmbedder
from ragline.ingestion.worker import BatchWorker, spawn_background
from ragline.llm.base import BaseLLM
from ragline.parsing.registry import supported_extensions
from ragline.storage.file_store import BaseFileStore
from ragline.storage.metadata_db import (
    count_batch_stages,
    create_batch,
    create_document,
    get_batch,
    get_batch_documents,
    list_batches,
    update_batch,
)
from ragline.storage.paths import join_original_path
from ragline.vectorstore.base import BaseVectorStore

log = structlog.get_logger()
router = APIRouter(prefix="/batches", tags=["batches"])


def _is_hidden_or_ignored(path_str: str) -> bool:
    """True for dot-files/dirs and macOS ZIP artifacts (__MACOSX)."""
    parts = PurePosixPath(path_str).parts
    return any(p.startswith(".") or p in ("__MACOSX",) for p in parts)


def _sanitize_rel_path(name: str) -> str:
    """Strip traversal ('..', '.', root) segments from an upload-relative path.

    Applied to BOTH ZIP entries and individual multipart filenames — a crafted
    filename must never resolve outside the upload dir (the file store re-checks
    too, but this keeps a bad name from ever reaching it). Returns "" when
    nothing usable remains.
    """
    parts = [p for p in PurePosixPath(name.replace("\\", "/")).parts if p not in ("..", ".", "/")]
    return str(PurePosixPath(*parts)) if parts else ""


@router.post("/upload", response_model=BatchUploadResponse)
async def batch_upload(
    files: list[UploadFile] = File(default=[]),
    zip_file: UploadFile | None = None,
    # Optional provenance: the folder these files were copied FROM
    # (e.g. \\server\share\ProjectA). Joined with each relative path.
    original_base_path: str = Form(default=""),
    file_store: BaseFileStore = Depends(get_file_store),
    embedder: BaseEmbedder = Depends(get_embedder),
    vector_store: BaseVectorStore = Depends(get_vector_store),
    pipeline=Depends(get_retrieval_pipeline),
    llm: BaseLLM = Depends(get_llm),
    user: AuthedUser = Depends(get_current_user),
):
    """Upload multiple files or a ZIP archive for batch ingestion."""
    # Collected (relative_path, bytes) pairs from both input styles.
    file_entries: list[tuple[str, bytes]] = []
    skipped_unsupported: list[str] = []
    supported = supported_extensions()

    # --- ZIP archive: unpack in memory ------------------------------------
    if zip_file and zip_file.filename:
        zip_data = await zip_file.read()
        try:
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                for name in zf.namelist():
                    # Directory entries carry no data.
                    if name.endswith("/"):
                        continue
                    # Skip hidden files and macOS resource forks.
                    if _is_hidden_or_ignored(name):
                        continue
                    # Unsupported types are reported, not fatal.
                    ext = Path(name).suffix.lower()
                    if ext not in supported:
                        skipped_unsupported.append(name)
                        continue
                    # Neutralize any ".."/"." segments in the archive path
                    # (defense-in-depth; the file store re-checks traversal).
                    safe_name = _sanitize_rel_path(name)
                    if not safe_name:
                        skipped_unsupported.append(name)
                        continue
                    file_entries.append((safe_name, zf.read(name)))
        except zipfile.BadZipFile:
            raise HTTPException(400, "Invalid zip file")

    # --- individual multipart files ----------------------------------------
    for f in files:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in supported:
            skipped_unsupported.append(f.filename)
            continue
        # Sanitize like ZIP entries — a multipart filename can also carry
        # "../" and must not escape the upload dir.
        safe_name = _sanitize_rel_path(f.filename)
        if not safe_name:
            skipped_unsupported.append(f.filename)
            continue
        data = await f.read()
        file_entries.append((safe_name, data))

    # Nothing usable in the whole upload -> client error.
    if not file_entries:
        raise HTTPException(400, "No supported files provided")

    # Enforce the configured batch size cap.
    if len(file_entries) > settings.batch_max_files:
        raise HTTPException(
            400,
            f"Too many files ({len(file_entries)}). Maximum is {settings.batch_max_files}.",
        )

    # One batch row; one Document row per accepted file.
    batch = await create_batch(total_files=len(file_entries))

    created = 0
    for rel_path, data in file_entries:
        try:
            file_hash = hashlib.sha256(data).hexdigest()
            filename = Path(rel_path).name
            ext = Path(filename).suffix.lower()

            # Managed copy stored under "{batch_id}/{rel_path}" — this storage
            # path becomes Document.filename (the worker resolves files by it).
            storage_path = f"{batch.id}/{rel_path}"
            await file_store.save(storage_path, data)

            await create_document(
                filename=storage_path,
                file_type=ext.lstrip("."),
                file_hash=file_hash,
                batch_id=batch.id,
                source_path=rel_path,
                # Provenance: base + relative path, UNC-aware ("" when no base).
                original_path=join_original_path(original_base_path, rel_path) if original_base_path.strip() else "",
                uploaded_by=user.upn,
            )
            created += 1
        except Exception as e:
            # Isolate per-file failures (bad path, disk error) so one bad file
            # never aborts the whole upload — mirrors the ingestion worker's
            # per-document isolation.
            log.warning("skipping unprocessable upload file", file=rel_path, error=str(e))
            skipped_unsupported.append(rel_path)

    # Nothing stored -> client error rather than an empty orphan batch.
    if created == 0:
        raise HTTPException(400, "No files could be stored from this upload")
    # Keep the counter honest: the worker only processes what was created.
    if created != len(file_entries):
        await update_batch(batch.id, total_files=created)

    # Process the whole batch in the background.
    worker = BatchWorker(file_store, embedder, vector_store, pipeline, llm=llm)
    spawn_background(worker.process_batch(batch.id))

    return BatchUploadResponse(
        batch_id=batch.id,
        total_files=created,
        skipped_unsupported=skipped_unsupported,
    )


def _resolve_ingest_dir(raw_path: str) -> Path:
    """Validate a server-folder ingest path against the INGEST_ROOTS allowlist.

    Fully resolves the requested path (symlinks and '..' collapse here, so a
    link pointing outside a root fails the containment check) and requires it
    to sit inside one of the resolved allowlist roots. Raises HTTPException:
    400 when the feature is disabled or the path isn't a directory, 403 when
    the path escapes every allowlisted root.
    """
    roots = settings.ingest_roots_list
    # Feature is opt-in: with no roots configured the endpoint refuses all work.
    if not roots:
        raise HTTPException(400, "Server-folder ingest is disabled (INGEST_ROOTS is not set)")
    target = Path(raw_path).expanduser().resolve()
    if not target.is_dir():
        raise HTTPException(400, f"Not a directory on the server: {raw_path}")
    for root in roots:
        # Roots resolve at request time so allowlist symlink changes apply
        # without a restart; is_relative_to gives strict containment.
        if target.is_relative_to(Path(root).expanduser().resolve()):
            return target
    raise HTTPException(403, "Path is outside the allowed ingest roots")


@router.post("/ingest-path", response_model=BatchUploadResponse)
async def ingest_path(
    body: IngestPathRequest,
    file_store: BaseFileStore = Depends(get_file_store),
    embedder: BaseEmbedder = Depends(get_embedder),
    vector_store: BaseVectorStore = Depends(get_vector_store),
    pipeline=Depends(get_retrieval_pipeline),
    llm: BaseLLM = Depends(get_llm),
    user: AuthedUser = Depends(get_current_user),
):
    """Ingest a server-local folder without moving its bytes over HTTP.

    The browser upload path reads every file into request memory — fine for
    interactive uploads, hopeless for a multi-GB corpus. This route walks an
    allowlisted directory, then enqueues + processes the files in a background
    task that streams them from disk ONE AT A TIME, so memory stays flat and
    the request returns as soon as the batch exists (the UI attaches to the
    batch id and watches progress exactly as it does for uploads).
    """
    target = _resolve_ingest_dir(body.path)

    # Walk up front (cheap) so the response carries the real file count and
    # empty/oversized requests fail before any batch row exists. Same filters
    # as the ZIP path: supported extensions only, hidden/junk paths skipped.
    supported = supported_extensions()
    rel_paths: list[str] = []
    skipped_unsupported: list[str] = []
    for p in sorted(target.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(target).as_posix()
        if _is_hidden_or_ignored(rel):
            continue
        if p.suffix.lower() not in supported:
            skipped_unsupported.append(rel)
            continue
        rel_paths.append(rel)

    if not rel_paths:
        raise HTTPException(400, f"No supported files found under {body.path}")
    if len(rel_paths) > settings.batch_max_files:
        raise HTTPException(
            400,
            f"Too many files ({len(rel_paths)}). Maximum is {settings.batch_max_files}.",
        )

    batch = await create_batch(total_files=len(rel_paths))
    original_base = body.original_base_path.strip()
    uploader = user.upn  # bound now; the request context is gone when the task runs

    async def enqueue_and_process() -> None:
        """Copy files into the store one at a time, then run the batch.

        Runs in the background so the HTTP request doesn't block on the
        multi-GB disk copy. Document rows appear progressively (the UI shows
        the list growing), and process_batch starts only after the last row
        exists — it snapshots pending documents once at start.
        """
        created = 0
        for rel_path in rel_paths:
            try:
                # One file resident at a time — this is the whole point.
                data = (target / rel_path).read_bytes()
                await file_store.save(f"{batch.id}/{rel_path}", data)
                await create_document(
                    filename=f"{batch.id}/{rel_path}",
                    file_type=Path(rel_path).suffix.lower().lstrip("."),
                    file_hash=hashlib.sha256(data).hexdigest(),
                    batch_id=batch.id,
                    source_path=rel_path,
                    # Provenance mirrors the upload route: base + relative path.
                    original_path=join_original_path(original_base, rel_path) if original_base else "",
                    # Captured at request time; this loop runs detached later.
                    uploaded_by=uploader,
                )
                created += 1
            except Exception as e:
                # Per-file isolation, as in the upload loop: a vanished or
                # unreadable file must not abort the corpus run.
                log.warning("skipping unreadable ingest-path file", file=rel_path, error=str(e))
        # Keep the batch counter honest when files failed to enqueue.
        if created != len(rel_paths):
            await update_batch(batch.id, total_files=created)
        if created == 0:
            # Nothing enqueued: close the batch out rather than leave it
            # 'pending' forever (process_batch would find no documents).
            await update_batch(batch.id, status="completed_with_errors")
            return
        worker = BatchWorker(file_store, embedder, vector_store, pipeline, llm=llm)
        await worker.process_batch(batch.id)

    spawn_background(enqueue_and_process())

    return BatchUploadResponse(
        batch_id=batch.id,
        total_files=len(rel_paths),
        skipped_unsupported=skipped_unsupported,
    )


@router.get("/{batch_id}", response_model=BatchStatusResponse)
async def batch_status(
    batch_id: str,
    include_documents: bool = True,
    user: AuthedUser = Depends(get_current_user),
):
    """Batch status with per-document stage detail (polled by the UI).

    ?include_documents=false returns counters + per-stage aggregates only —
    the fast-poll variant, so a big batch isn't serialized in full every tick.
    original_path is per-user data (same ACL gate as citations) and blanked
    for documents whose source the requester can't reach.
    """
    from ragline.acl.access import accessible_document_ids

    batch = await get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    docs = await get_batch_documents(batch_id) if include_documents else []
    stages = await count_batch_stages(batch_id)
    allowed = await accessible_document_ids(user, [d.id for d in docs])

    return BatchStatusResponse(
        id=batch.id,
        created_at=batch.created_at.isoformat(),
        total_files=batch.total_files,
        completed_files=batch.completed_files,
        failed_files=batch.failed_files,
        skipped_files=batch.skipped_files,
        status=batch.status,
        stages=stages,
        documents=[
            BatchDocumentSchema(
                id=d.id,
                # Display just the basename; source_path keeps the full
                # relative path for disambiguation.
                filename=Path(d.source_path).name if d.source_path else d.filename,
                file_type=d.file_type,
                status=d.status,
                source_path=d.source_path,
                original_path=d.original_path if d.id in allowed else "",
                page_count=d.page_count,
                chunk_count=d.chunk_count,
                stage=d.stage,
            )
            for d in docs
        ],
    )


@router.get("", response_model=list[BatchListItem])
async def list_all_batches():
    """All ingestion batches, newest first."""
    batches = await list_batches()
    return [
        BatchListItem(
            id=b.id,
            created_at=b.created_at.isoformat(),
            total_files=b.total_files,
            completed_files=b.completed_files,
            failed_files=b.failed_files,
            skipped_files=b.skipped_files,
            status=b.status,
        )
        for b in batches
    ]
