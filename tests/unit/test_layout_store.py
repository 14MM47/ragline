"""Explorer layout store — coordinate validation and the folder/placement
rules, run against a throwaway SQLite file so the real rules execute."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ragline.storage import layout
from ragline.storage.layout import (
    DocumentFolder,
    DocumentPlacement,
    LayoutError,
    normalize_folder_path,
    normalize_root,
)

# --- validation --------------------------------------------------------------


def test_normalize_root_trims_and_rejects_blank():
    assert normalize_root("  \\\\fs1\\share ") == "\\\\fs1\\share"
    with pytest.raises(LayoutError):
        normalize_root("   ")
    with pytest.raises(LayoutError):
        normalize_root("bad\x00root")


def test_normalize_folder_path_canonical_form():
    """Windows separators, stray slashes and padding all collapse to a/b."""
    assert normalize_folder_path("/a\\b//c /") == "a/b/c"
    assert normalize_folder_path("") == ""
    assert normalize_folder_path("   ") == ""
    with pytest.raises(LayoutError):
        normalize_folder_path("a/../b")
    with pytest.raises(LayoutError):
        normalize_folder_path("a/./b")


# --- store rules (real SQLite in a temp dir) ---------------------------------


@pytest.fixture
async def store(tmp_path, monkeypatch):
    """Point the layout module at a fresh database holding just its tables."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'layout.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(DocumentFolder.__table__.create)
        await conn.run_sync(DocumentPlacement.__table__.create)
    monkeypatch.setattr(layout, "_async_session", sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))
    yield layout
    await engine.dispose()


async def test_create_folder_is_idempotent(store):
    a = await store.create_folder("Projects", "site-b/plc", created_by="u1")
    b = await store.create_folder("Projects", "site-b\\plc", created_by="u2")
    assert (a.root, a.folder_path) == ("Projects", "site-b/plc")
    # Same coordinates (after normalisation) -> the original row, first creator kept.
    assert b.created_by == "u1"
    assert len(await store.list_folders()) == 1


async def test_delete_empty_folder(store):
    await store.create_folder("Projects", "old", created_by="u1")
    assert await store.delete_folder("Projects", "old") is True
    assert await store.list_folders() == []
    # Gone already -> False, so the route can answer 404.
    assert await store.delete_folder("Projects", "old") is False


async def test_delete_blocked_by_placement_beneath(store):
    await store.create_folder("Projects", "keep", created_by="u1")
    await store.set_placement("doc-1", "Projects", "keep/deeper", moved_by="u1")
    with pytest.raises(LayoutError, match="moved documents"):
        await store.delete_folder("Projects", "keep")
    # Clearing the placement unblocks it.
    assert await store.clear_placement("doc-1") is True
    assert await store.delete_folder("Projects", "keep") is True


async def test_delete_blocked_by_subfolder(store):
    await store.create_folder("Projects", "a", created_by="u1")
    await store.create_folder("Projects", "a/b", created_by="u1")
    with pytest.raises(LayoutError, match="sub-folders"):
        await store.delete_folder("Projects", "a")
    # A sibling with a common prefix is NOT beneath it ("ab" vs "a").
    await store.create_folder("Projects", "ab", created_by="u1")
    assert await store.delete_folder("Projects", "a/b") is True
    assert await store.delete_folder("Projects", "a") is True


async def test_placement_replaces_and_clears(store):
    first = await store.set_placement("doc-1", "Projects", "x", moved_by="u1")
    second = await store.set_placement("doc-1", "Archive", "", moved_by="u2")
    assert first.document_id == second.document_id == "doc-1"
    rows = await store.list_placements()
    assert len(rows) == 1
    assert (rows[0].root, rows[0].folder_path, rows[0].moved_by) == ("Archive", "", "u2")
    assert await store.clear_placement("doc-1") is True
    assert await store.clear_placement("doc-1") is False
    assert await store.list_placements() == []


async def test_folder_cap(store, monkeypatch):
    """The global folder ceiling refuses new rows but still returns existing ones."""
    monkeypatch.setattr(store, "MAX_FOLDERS", 2)
    await store.create_folder("A", "one", created_by="u1")
    await store.create_folder("A", "two", created_by="u1")
    with pytest.raises(LayoutError, match="folder limit"):
        await store.create_folder("A", "three", created_by="u1")
    # Idempotent re-create of an existing folder is not a new row.
    assert (await store.create_folder("A", "one", created_by="u2")).created_by == "u1"
