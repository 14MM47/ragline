"""Explorer layout — user-created folders and document placements.

NEW in ragline (no raggles equivalent). The Documents tab's folder view is
DERIVED from each document's upload coordinates (see paths.upload_root /
folder_path). This module stores the two things users add on top of that:

  DocumentFolder     a folder the user created in the explorer (it may be
                     empty, which is why it needs a row — derived folders
                     exist only while a document sits in them)
  DocumentPlacement  "show document X in folder Y instead of where it was
                     uploaded from"

Both are addressed by the same coordinate pair the derived tree uses:
`root` (a top-level node: an upload share, a batch label, or a name the
user typed) and `folder_path` ("/"-separated, "" = directly under the root).
Keying by path string rather than folder id keeps virtual folders and
derived folders interchangeable — a document can be moved into either.

The layout is SHARED between users (documents are global in ragline); a
per-user split is a later version. Nothing here touches ingestion, Qdrant,
the file store or the BM25 index — it is purely how the tab is drawn.
"""

from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlmodel import Field, SQLModel

from ragline.storage.metadata_db import _async_session

# Bounds on user-typed coordinates: generous, but not unbounded TEXT.
MAX_ROOT_LEN = 512
MAX_FOLDER_LEN = 1024
# Global ceiling on user-created folders. Documents may run to thousands;
# folders are hand-made and a few thousand is already an unusable tree, so
# the cap only stops a runaway client bloating the table.
MAX_FOLDERS = 5000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocumentFolder(SQLModel, table=True):
    """A user-created explorer folder (composite key = its tree coordinates)."""

    __tablename__ = "document_folder"

    root: str = Field(primary_key=True)
    folder_path: str = Field(primary_key=True)
    created_by: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class DocumentPlacement(SQLModel, table=True):
    """Where a document is shown instead of its derived upload location."""

    __tablename__ = "document_placement"

    document_id: str = Field(primary_key=True, foreign_key="document.id")
    root: str = Field(index=True)
    folder_path: str = ""
    moved_by: str = ""
    moved_at: datetime = Field(default_factory=_utcnow)


class LayoutError(ValueError):
    """A coordinate failed validation — surfaces as a 400 at the API layer."""


def normalize_root(root: str) -> str:
    """Trim and bound a root name; reject blanks and control characters."""
    value = root.strip()
    if not value:
        raise LayoutError("root must not be blank")
    if len(value) > MAX_ROOT_LEN:
        raise LayoutError(f"root longer than {MAX_ROOT_LEN} characters")
    if any(ord(ch) < 32 for ch in value):
        raise LayoutError("root contains control characters")
    return value


def normalize_folder_path(folder_path: str) -> str:
    """Canonical "/"-separated folder path: trimmed segments, no dot-segments.

    Backslashes are treated as separators (pasted Windows paths), empty
    segments collapse, and "" means "directly under the root".
    """
    raw = folder_path.replace("\\", "/")
    segments = [seg.strip() for seg in raw.split("/")]
    segments = [seg for seg in segments if seg]
    for seg in segments:
        if seg in (".", ".."):
            raise LayoutError("folder path may not contain '.' or '..' segments")
        if any(ord(ch) < 32 for ch in seg):
            raise LayoutError("folder path contains control characters")
    value = "/".join(segments)
    if len(value) > MAX_FOLDER_LEN:
        raise LayoutError(f"folder path longer than {MAX_FOLDER_LEN} characters")
    return value


def _is_under(folder_path: str, parent: str) -> bool:
    """True when folder_path is `parent` itself or nested inside it."""
    return folder_path == parent or folder_path.startswith(parent + "/")


# --- Queries ----------------------------------------------------------------


async def list_folders() -> list[DocumentFolder]:
    """Every user-created folder, in a stable order."""
    async with _async_session() as session:
        result = await session.execute(
            select(DocumentFolder).order_by(DocumentFolder.root, DocumentFolder.folder_path)
        )
        return list(result.scalars().all())


async def list_placements() -> list[DocumentPlacement]:
    """Every explicit placement (one per moved document)."""
    async with _async_session() as session:
        result = await session.execute(select(DocumentPlacement))
        return list(result.scalars().all())


# --- Folders ----------------------------------------------------------------


async def create_folder(root: str, folder_path: str, created_by: str) -> DocumentFolder:
    """Create a folder row; a duplicate is a no-op returning the existing row."""
    root = normalize_root(root)
    # folder_path "" is allowed: an empty top-level folder is a row with a
    # blank path, which the tree renders as an empty root.
    folder_path = normalize_folder_path(folder_path)
    async with _async_session() as session:
        existing = await session.get(DocumentFolder, (root, folder_path))
        if existing:
            return existing
        count = (await session.execute(select(func.count()).select_from(DocumentFolder))).scalar_one()
        if count >= MAX_FOLDERS:
            raise LayoutError(f"folder limit reached ({MAX_FOLDERS})")
        row = DocumentFolder(root=root, folder_path=folder_path, created_by=created_by)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def delete_folder(root: str, folder_path: str) -> bool:
    """Delete a user-created folder. Only when nothing is placed in or under it.

    Returns False when no such folder row exists. Raises LayoutError when a
    placement or a user-created sub-folder still lives beneath it — the
    caller decides whether derived documents also block the delete (they
    are not visible from here without the per-user listing).
    """
    root = normalize_root(root)
    folder_path = normalize_folder_path(folder_path)
    async with _async_session() as session:
        row = await session.get(DocumentFolder, (root, folder_path))
        if row is None:
            return False
        placed = (
            await session.execute(select(DocumentPlacement).where(DocumentPlacement.root == root))
        ).scalars().all()
        if any(_is_under(p.folder_path, folder_path) for p in placed):
            raise LayoutError("folder still contains moved documents")
        subs = (
            await session.execute(select(DocumentFolder).where(DocumentFolder.root == root))
        ).scalars().all()
        if any(f.folder_path != folder_path and _is_under(f.folder_path, folder_path) for f in subs):
            raise LayoutError("folder still contains sub-folders")
        await session.delete(row)
        await session.commit()
        return True


# --- Placements -------------------------------------------------------------


async def set_placement(document_id: str, root: str, folder_path: str, moved_by: str) -> DocumentPlacement:
    """Move a document to (root, folder_path); replaces any earlier placement."""
    root = normalize_root(root)
    folder_path = normalize_folder_path(folder_path)
    async with _async_session() as session:
        row = await session.get(DocumentPlacement, document_id)
        if row is None:
            row = DocumentPlacement(document_id=document_id, root=root, folder_path=folder_path, moved_by=moved_by)
            session.add(row)
        else:
            row.root = root
            row.folder_path = folder_path
            row.moved_by = moved_by
            row.moved_at = _utcnow()
        await session.commit()
        await session.refresh(row)
        return row


async def clear_placement(document_id: str) -> bool:
    """Put a document back at its derived location. True if a row was removed."""
    async with _async_session() as session:
        result = await session.execute(
            delete(DocumentPlacement).where(DocumentPlacement.document_id == document_id)
        )
        await session.commit()
        return (result.rowcount or 0) > 0
