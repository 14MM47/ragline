"""Explorer-layout routes — user folders and document placements.

NEW in ragline. Backs the Documents tab's "New folder" / "Move to" actions:

  GET    /documents/layout                         folders + placements
  POST   /documents/layout/folders                 create a folder
  DELETE /documents/layout/folders                 delete an EMPTY folder
  PUT    /documents/layout/placements/{doc_id}     move a document
  DELETE /documents/layout/placements/{doc_id}     back to its upload location

The layout is shared, so any signed-in user may edit it (document deletion
keeps its owner-or-admin rule; per-user layouts and creator-or-admin folder
deletion are deferred to the multi-user layout version). Visibility still
follows the ACL — see api/explorer.py for the root rule.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException

from ragline.api.explorer import build_explorer, layout_for
from ragline.api.schemas import FolderRef, LayoutFolderSchema, LayoutPlacementSchema, LayoutResponse
from ragline.auth.dependencies import AuthedUser, get_current_user
from ragline.storage import layout as layout_store
from ragline.storage.layout import LayoutError
from ragline.storage.metadata_db import get_document

log = structlog.get_logger()
router = APIRouter(prefix="/documents/layout", tags=["documents"])


@router.get("", response_model=LayoutResponse)
async def get_layout(user: AuthedUser = Depends(get_current_user)):
    """User folders and placements this user may see (see api/explorer.py)."""
    view = await build_explorer(user)
    return layout_for(view, await layout_store.list_folders(), await layout_store.list_placements())


@router.post("/folders", response_model=LayoutFolderSchema, status_code=201)
async def create_folder(body: FolderRef, user: AuthedUser = Depends(get_current_user)):
    """Create an explorer folder (idempotent: an existing one is returned)."""
    try:
        row = await layout_store.create_folder(body.root, body.folder_path, created_by=user.upn)
    except LayoutError as exc:
        raise HTTPException(400, str(exc)) from exc
    log.info("explorer folder created", root=row.root, folder_path=row.folder_path, by=user.upn)
    return LayoutFolderSchema(root=row.root, folder_path=row.folder_path, created_by=row.created_by)


@router.delete("/folders")
async def delete_folder(body: FolderRef, user: AuthedUser = Depends(get_current_user)):
    """Delete a user-created folder that has nothing in it.

    409 when a moved document or another user folder is still inside it. The
    front end only offers Delete on folders it renders empty, which also
    covers derived documents (those never sit in a user folder unless a
    placement put them there, and placements are checked here).
    """
    try:
        removed = await layout_store.delete_folder(body.root, body.folder_path)
    except LayoutError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not removed:
        raise HTTPException(404, "Folder not found")
    log.info("explorer folder deleted", root=body.root, folder_path=body.folder_path, by=user.upn)
    return {"status": "deleted"}


@router.put("/placements/{document_id}", response_model=LayoutPlacementSchema)
async def move_document(document_id: str, body: FolderRef, user: AuthedUser = Depends(get_current_user)):
    """Show a document under (root, folder_path) instead of its upload location."""
    if await get_document(document_id) is None:
        raise HTTPException(404, "Document not found")
    try:
        row = await layout_store.set_placement(document_id, body.root, body.folder_path, moved_by=user.upn)
    except LayoutError as exc:
        raise HTTPException(400, str(exc)) from exc
    log.info("document moved", document_id=document_id, root=row.root, folder_path=row.folder_path, by=user.upn)
    return LayoutPlacementSchema(document_id=row.document_id, root=row.root, folder_path=row.folder_path)


@router.delete("/placements/{document_id}")
async def unmove_document(document_id: str, user: AuthedUser = Depends(get_current_user)):
    """Put a document back where it was uploaded from (no-op if never moved)."""
    removed = await layout_store.clear_placement(document_id)
    log.info("document placement cleared", document_id=document_id, removed=removed, by=user.upn)
    return {"status": "cleared", "removed": removed}
