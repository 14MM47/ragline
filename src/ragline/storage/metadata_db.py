"""Metadata database — SQLite via SQLModel, async throughout.

Ported from raggles with three deliberate changes:
  * Document gains `original_path` — the network location the file was
    uploaded FROM, surfaced in citations ("where does this really live?").
  * access_groups / enriched dropped (no auth, no contextual enrichment in v1).
  * No Alembic yet — tables come from create_all (plus the small in-place
    micro-migrations below); a baseline migration waits on a schema freeze.

Also home to `get_library_summary()`, the backbone of "library mode": chat
questions ABOUT the database (how many documents? what do you have on X?)
are answered from these tables, with no vector retrieval at all.
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import Field, SQLModel, col

from ragline.config import settings

log = structlog.get_logger()


class IngestionBatch(SQLModel, table=True):
    """One upload batch (a single file upload is a batch of 1)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Progress counters the BatchProgress UI polls.
    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    skipped_files: int = 0
    # pending -> processing -> completed | completed_with_errors
    status: str = "pending"


class Document(SQLModel, table=True):
    """One ingested document (one row per version)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    filename: str = Field(index=True)
    file_type: str
    upload_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # SHA-256 of the file bytes — powers duplicate detection on re-upload.
    file_hash: str = ""
    page_count: int = 0
    chunk_count: int = 0
    # pending -> processing -> ready | error | skipped_duplicate
    status: str = "pending"
    batch_id: str | None = Field(default=None, foreign_key="ingestionbatch.id", index=True)
    # Relative path within the uploaded ZIP/folder (also the version-chain key).
    source_path: str = ""
    # NEW in ragline: the ORIGINAL network location this file was uploaded
    # from (e.g. \\server\share\ProjectA\vfd\acs880_manual.pdf). Never used
    # for serving content — purely provenance, displayed in citations with a
    # copy-to-clipboard action. Deliberately NOT in the Qdrant payload so it
    # can be corrected later without re-ingesting.
    original_path: str = ""
    # Per-document ingestion progress: parsing, chunking, embedding, storing,
    # extracting_graph — the BatchProgress UI shows this live.
    stage: str = ""
    # Optional free-text uploader identity (no auth in v1).
    uploaded_by: str = ""
    # Version chain: same source_path, incrementing version numbers.
    version: int = 1
    previous_version_id: str | None = Field(default=None, index=True)


class ChunkRecord(SQLModel, table=True):
    """SQLite mirror of each chunk's source coordinates.

    The full chunk (text + vector) lives in Qdrant; this row exists so the
    metadata DB can answer structural questions (chunks per document, page
    spans) without touching the vector store.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    document_id: str = Field(index=True, foreign_key="document.id")
    chunk_index: int
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    section_header: str = ""


def _ensure_sqlite_dir(url: str) -> None:
    """Create the parent directory for a file-based SQLite database.

    SQLite refuses to create the database file if its directory is missing,
    which would break first run on a fresh clone (./data/ is gitignored).
    """
    # Only file-based SQLite URLs need this.
    if "sqlite" not in url:
        return
    path_part = url.rsplit("///", 1)[-1]
    if not path_part or path_part == ":memory:" or path_part.startswith("file:"):
        return
    from pathlib import Path

    Path(path_part).expanduser().parent.mkdir(parents=True, exist_ok=True)


# Engine + session factory built once at import (same pattern as raggles).
# busy_timeout: the ACL crawler is a SECOND PROCESS writing this database
# while the app serves — without a timeout, overlapping writes surface as
# instant "database is locked" errors instead of a short wait.
_ensure_sqlite_dir(settings.database_url)
_connect_args = {"timeout": 30} if "sqlite" in settings.database_url else {}
_engine = create_async_engine(settings.database_url, echo=False, connect_args=_connect_args)
_async_session = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Create all tables. Called from the app lifespan at startup."""
    # Import model modules that live elsewhere so create_all sees them.
    import ragline.knowledge_graph.models  # noqa: F401
    import ragline.storage.acl_models  # noqa: F401
    import ragline.storage.auth_models  # noqa: F401
    import ragline.storage.layout  # noqa: F401
    import ragline.tracing.models  # noqa: F401

    # create_all is idempotent — existing tables are left untouched.
    async with _engine.begin() as conn:
        # WAL lets the ACL crawler (a separate process) write while the app
        # reads and vice versa. The pragma is persistent — setting it at every
        # startup is a harmless no-op after the first time.
        if "sqlite" in settings.database_url:
            from sqlalchemy import text

            await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(SQLModel.metadata.create_all)

        # Micro-migrations (Alembic is deferred): create_all never ALTERs an
        # existing table, so columns added after a table first shipped are
        # patched in here. Idempotent — skipped once the column exists.
        if "sqlite" in settings.database_url:
            from sqlalchemy import text

            _added_columns = [
                ("document_acl", "denied_json", "TEXT DEFAULT '[]'"),
                ("auth_session", "refresh_token_enc", "TEXT DEFAULT ''"),
                # NULL default = "never validated": pre-migration sessions have
                # no refresh token to validate with, so they fail closed into
                # one re-login rather than silently skipping revocation checks.
                ("auth_session", "validated_at", "TIMESTAMP"),
                ("querytrace", "step_ms", "TEXT DEFAULT '{}'"),
            ]
            for table, column, ddl in _added_columns:
                cols = [
                    row[1]
                    for row in (
                        await conn.execute(text(f"PRAGMA table_info({table})"))
                    ).all()
                ]
                if cols and column not in cols:
                    await conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                    )
                    log.info("micro-migration applied", table=table, column=column)

    log.info("database initialized")


async def get_session() -> AsyncSession:
    """FastAPI dependency yielding one session per request."""
    async with _async_session() as session:
        yield session


# --- Document CRUD ----------------------------------------------------------


async def create_document(
    filename: str,
    file_type: str,
    file_hash: str = "",
    batch_id: str | None = None,
    source_path: str = "",
    original_path: str = "",
    uploaded_by: str = "",
) -> Document:
    """Insert a new Document row (status starts at 'pending')."""
    doc = Document(
        filename=filename,
        file_type=file_type,
        file_hash=file_hash,
        batch_id=batch_id,
        source_path=source_path,
        original_path=original_path,
        uploaded_by=uploaded_by,
    )
    async with _async_session() as session:
        session.add(doc)
        await session.commit()
        # refresh() re-reads generated defaults (id, upload_date).
        await session.refresh(doc)
    return doc


async def update_document(doc_id: str, **kwargs) -> None:
    """Set arbitrary fields on a document (used for status/stage updates)."""
    async with _async_session() as session:
        result = await session.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalars().one()
        for k, v in kwargs.items():
            setattr(doc, k, v)
        session.add(doc)
        await session.commit()


async def get_document(doc_id: str) -> Document | None:
    """Fetch one document by id, or None."""
    async with _async_session() as session:
        result = await session.execute(select(Document).where(Document.id == doc_id))
        return result.scalars().first()


async def get_all_ready_documents() -> list[Document]:
    """Every ready document — the ACL crawler's work list.

    Only 'ready' rows matter: unfinished/errored ingests have no servable
    content, so there is nothing to gate yet.
    """
    async with _async_session() as session:
        result = await session.execute(select(Document).where(Document.status == "ready"))
        return list(result.scalars().all())


async def get_documents_by_ids(doc_ids: list[str]) -> dict[str, Document]:
    """Fetch several documents at once, keyed by id.

    Used by the chat route to enrich cited sources with original_path in a
    single query after citation extraction.
    """
    if not doc_ids:
        return {}
    async with _async_session() as session:
        result = await session.execute(select(Document).where(col(Document.id).in_(doc_ids)))
        return {doc.id: doc for doc in result.scalars().all()}


async def list_documents() -> list[Document]:
    """All documents, newest first (Documents tab listing)."""
    async with _async_session() as session:
        result = await session.execute(
            select(Document).order_by(col(Document.upload_date).desc())
        )
        return list(result.scalars().all())


async def delete_document(doc_id: str) -> None:
    """Delete a document row plus its chunk records."""
    async with _async_session() as session:
        # Chunk records first (no DB-level cascade configured).
        result = await session.execute(
            select(ChunkRecord).where(ChunkRecord.document_id == doc_id)
        )
        for chunk in result.scalars().all():
            await session.delete(chunk)
        # Then the document itself.
        result = await session.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalars().first()
        if doc:
            await session.delete(doc)
        await session.commit()


async def delete_chunk_records(doc_id: str) -> None:
    """Delete a document's chunk records but KEEP the document row.

    Used by retry: a failed ingest may have written some chunks before dying,
    and re-processing appends rather than replaces, so the partial rows must go
    first. delete_document() is the wrong tool here — it removes the row we are
    about to reset to 'pending'.
    """
    async with _async_session() as session:
        result = await session.execute(
            select(ChunkRecord).where(ChunkRecord.document_id == doc_id)
        )
        for chunk in result.scalars().all():
            await session.delete(chunk)
        await session.commit()


async def save_chunk_records(document_id: str, chunks) -> None:
    """Persist the SQLite mirror rows for a document's chunks."""
    async with _async_session() as session:
        for chunk in chunks:
            record = ChunkRecord(
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                section_header=chunk.section_header,
            )
            session.add(record)
        await session.commit()


# --- Batch functions --------------------------------------------------------


async def create_batch(total_files: int) -> IngestionBatch:
    """Insert a new batch row."""
    batch = IngestionBatch(total_files=total_files)
    async with _async_session() as session:
        session.add(batch)
        await session.commit()
        await session.refresh(batch)
    return batch


async def update_batch(batch_id: str, **kwargs) -> None:
    """Set arbitrary fields on a batch (status transitions)."""
    async with _async_session() as session:
        result = await session.execute(
            select(IngestionBatch).where(IngestionBatch.id == batch_id)
        )
        batch = result.scalars().one()
        for k, v in kwargs.items():
            setattr(batch, k, v)
        session.add(batch)
        await session.commit()


async def increment_batch_counter(batch_id: str, field: str) -> None:
    """Atomically bump one of the batch progress counters by 1.

    A single SQL ``SET field = field + 1`` — NOT read-modify-write in Python —
    so concurrent document tasks (up to batch_max_parallel) cannot interleave
    a stale read and lose an increment; SQLite serializes the statement.
    """
    column = getattr(IngestionBatch, field)
    async with _async_session() as session:
        await session.execute(
            update(IngestionBatch)
            .where(IngestionBatch.id == batch_id)
            .values({field: column + 1})
        )
        await session.commit()


async def get_batch(batch_id: str) -> IngestionBatch | None:
    """Fetch one batch by id, or None."""
    async with _async_session() as session:
        result = await session.execute(
            select(IngestionBatch).where(IngestionBatch.id == batch_id)
        )
        return result.scalars().first()


async def list_batches() -> list[IngestionBatch]:
    """All batches, newest first."""
    async with _async_session() as session:
        result = await session.execute(
            select(IngestionBatch).order_by(col(IngestionBatch.created_at).desc())
        )
        return list(result.scalars().all())


async def get_batch_documents(batch_id: str) -> list[Document]:
    """All documents belonging to one batch (BatchProgress polling)."""
    async with _async_session() as session:
        result = await session.execute(
            select(Document).where(Document.batch_id == batch_id)
        )
        return list(result.scalars().all())


async def count_batch_stages(batch_id: str) -> dict[str, int]:
    """Documents-per-stage counts for one batch (the UI's per-stage bars).

    A single GROUP BY over the in-flight documents (status='processing');
    completed/failed/skipped documents are already covered by the batch
    counters, so only live stages appear here. Cheap enough for a fast poll.
    """
    async with _async_session() as session:
        result = await session.execute(
            select(Document.stage, func.count())
            .where(Document.batch_id == batch_id)
            .where(Document.status == "processing")
            .group_by(Document.stage)
        )
        # Drop the pre-stage "" bucket (status flipped but no stage set yet).
        return {stage: n for stage, n in result.all() if stage}


async def find_unfinished_batches() -> list[IngestionBatch]:
    """Batches a previous process left mid-flight (startup requeue scan)."""
    async with _async_session() as session:
        result = await session.execute(
            select(IngestionBatch).where(
                col(IngestionBatch.status).in_(("pending", "processing"))
            )
        )
        return list(result.scalars().all())


async def find_document_by_hash(file_hash: str) -> Document | None:
    """Find an already-ready document with identical bytes (dedup check)."""
    async with _async_session() as session:
        result = await session.execute(
            select(Document)
            .where(Document.file_hash == file_hash, Document.status == "ready")
        )
        return result.scalars().first()


# --- Library mode / stats ---------------------------------------------------


def _display_name(doc: Document) -> str:
    """Human-facing name for a document — the upload-relative path.

    filename is stored as "{batch_id}/{rel_path}"; source_path holds just the
    rel_path. Prefer source_path; fall back to filename's basename so a stray
    batch-id prefix never reaches the library-mode prompt or the LLM's mental
    model of file names (which later drives excluded_sources matching).
    """
    if doc.source_path:
        return doc.source_path
    return doc.filename.replace("\\", "/").rsplit("/", 1)[-1]


def _group_by_category(docs: list[Document]) -> dict[str, list[Document]]:
    """Group documents by library category.

    Category = second segment of the upload-relative path when present
    (batch uploads keep folder structure, e.g. "vfd/abb/acs880.pdf" -> "abb"
    ... falling back to the first segment or 'uncategorised'). Use
    source_path, NOT filename: filename carries a "{batch_id}/" prefix, so
    keying off it would make every flat upload its own UUID "category".
    """
    categories: dict[str, list[Document]] = {}
    for doc in docs:
        rel = _display_name(doc)
        parts = rel.replace("\\", "/").split("/")
        category = parts[1] if len(parts) > 2 else parts[0] if len(parts) > 1 else "uncategorised"
        categories.setdefault(category, []).append(doc)
    return categories


async def _ready_documents() -> list[Document]:
    async with _async_session() as session:
        result = await session.execute(
            select(Document).where(Document.status == "ready")
        )
        return list(result.scalars().all())


def render_library_summary(docs: list[Document]) -> str:
    """The plain-text summary that goes into the library-mode LLM prompt."""
    if not docs:
        return "The document library is empty — no documents have been ingested yet."

    categories = _group_by_category(docs)

    # Library-wide totals first.
    total_docs = len(docs)
    total_pages = sum(d.page_count for d in docs)
    total_chunks = sum(d.chunk_count for d in docs)

    lines = [f"Library totals: {total_docs} documents, {total_pages} pages, {total_chunks} chunks\n"]
    # Then per-category breakdowns with every filename listed.
    for cat in sorted(categories):
        cat_docs = categories[cat]
        cat_pages = sum(d.page_count for d in cat_docs)
        cat_chunks = sum(d.chunk_count for d in cat_docs)
        lines.append(f"Category '{cat}' — {len(cat_docs)} docs, {cat_pages} pages, {cat_chunks} chunks:")
        for d in sorted(cat_docs, key=_display_name):
            lines.append(f"  - {_display_name(d)} ({d.page_count} pages, {d.chunk_count} chunks)")

    return "\n".join(lines)


def render_library_listing(docs: list[Document]) -> str:
    """The user-facing markdown file list, grouped by category.

    Shown verbatim in a chat answer in place of the model's file-list
    placeholder, so it is markdown and carries no chunk counts.
    """
    if not docs:
        return "The document library is empty — no documents have been ingested yet."

    categories = _group_by_category(docs)
    total_pages = sum(d.page_count for d in docs)
    lines = [f"**Library totals:** {len(docs):,} documents, {total_pages:,} pages"]
    for cat in sorted(categories):
        cat_docs = categories[cat]
        lines.append("")
        lines.append(f"### {cat} ({len(cat_docs)} docs)")
        for d in sorted(cat_docs, key=_display_name):
            lines.append(f"- `{_display_name(d)}` ({d.page_count} pages)")
    return "\n".join(lines)


async def get_library_summary() -> str:
    """Return a formatted summary of all ready documents, grouped by category.

    This string goes straight into the library-mode LLM prompt, so chat can
    answer "how many VFD manuals do you have?" from metadata alone.
    """
    return render_library_summary(await _ready_documents())


async def get_library_listing() -> str:
    """Return the markdown file list of all ready documents (no LLM involved)."""
    return render_library_listing(await _ready_documents())


async def get_document_stats() -> dict:
    """Aggregate counts for the health endpoint."""
    async with _async_session() as session:
        doc_result = await session.execute(
            select(Document).where(Document.status == "ready")
        )
        docs = list(doc_result.scalars().all())
    return {
        "document_count": len(docs),
        "chunk_count": sum(d.chunk_count for d in docs),
        "total_pages": sum(d.page_count for d in docs),
    }


# --- Versioning -------------------------------------------------------------


async def find_latest_version_by_name(source_path: str) -> Document | None:
    """Find the latest ready version of a document by its source path."""
    async with _async_session() as session:
        result = await session.execute(
            select(Document)
            .where(Document.source_path == source_path, Document.status == "ready")
            .order_by(col(Document.version).desc())
        )
        return result.scalars().first()


async def get_version_history(doc_id: str) -> list[Document]:
    """Full version chain for a document (newest first)."""
    async with _async_session() as session:
        # Resolve the document to learn its source_path (the chain key).
        result = await session.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalars().first()
        if not doc:
            return []

        # All versions share the same source_path.
        result = await session.execute(
            select(Document)
            .where(Document.source_path == doc.source_path)
            .order_by(col(Document.version).desc())
        )
        return list(result.scalars().all())
