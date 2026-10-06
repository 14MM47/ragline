"""Explorer view assembly — the per-user document rows plus root visibility.

NEW in ragline. Three endpoints need the same two facts about the caller:
which documents' network locations they may see (one ACL query) and, from
that, the per-row explorer coordinates and the set of tree roots they may be
shown. Computing it here ONCE per request means the combined
GET /documents/explorer costs a single document scan + ACL lookup, where the
separate /documents and /documents/layout calls used to do it twice per
poll. Both older endpoints remain and are built on the same helper.

Root visibility rule (the listing's original_path rule, applied to roots):
  * a root derived from some document's original_path is a network folder;
    it is served only to callers the ACL lets see at least one document
    at that root — otherwise even its NAME would leak the share;
  * batch labels are per-viewer (a hidden document sits under its batch
    label for one caller and under the share for another), gated the same
    way;
  * roots no document derives from were typed by a user and go to everyone.
"""

from dataclasses import dataclass, field

from ragline.acl import access as acl_access
from ragline.api.schemas import (
    DocumentSchema,
    LayoutFolderSchema,
    LayoutPlacementSchema,
    LayoutResponse,
)
from ragline.auth.dependencies import AuthedUser
from ragline.storage.metadata_db import list_documents
from ragline.storage.paths import folder_path, upload_root

# Root label for rows that predate batches (batch_id NULL).
NO_BATCH_LABEL = "Unfiled uploads"


@dataclass
class ExplorerView:
    """What one caller may see: the rows, and the roots the layout may name."""

    rows: list[DocumentSchema] = field(default_factory=list)
    # Roots present in THIS caller's rows.
    visible_roots: set[str] = field(default_factory=set)
    # Roots ANY document derives from, for any caller (network + batch labels).
    derived_roots: set[str] = field(default_factory=set)

    def serves(self, root: str) -> bool:
        """May this caller be shown a folder or placement under `root`?"""
        return root in self.visible_roots or root not in self.derived_roots


def batch_root_labels(docs) -> dict[str, str]:
    """Fallback explorer-root label per batch: "Upload <date> · <id8>".

    Used for documents whose upload root cannot be derived (no original path
    supplied, or hidden from this user by the ACL). The date is the earliest
    upload_date seen in the batch, so every row of a batch shares one label
    even when ingestion straddled midnight; the short id keeps two same-day
    uploads apart.
    """
    earliest: dict[str, object] = {}
    for d in docs:
        if not d.batch_id:
            continue
        cur = earliest.get(d.batch_id)
        if cur is None or d.upload_date < cur:
            earliest[d.batch_id] = d.upload_date
    return {bid: f"Upload {ts.strftime('%Y-%m-%d')} · {bid[:8]}" for bid, ts in earliest.items()}


async def build_explorer(user: AuthedUser) -> ExplorerView:
    """One document scan + one ACL query -> this caller's explorer view."""
    docs = await list_documents()
    allowed = await acl_access.accessible_document_ids(user, [d.id for d in docs])
    labels = batch_root_labels(docs)
    # Skipped duplicates point at the ready document holding the same bytes
    # (the worker's dedup rule: same file_hash, status ready).
    ready_by_hash = {d.file_hash: d.id for d in docs if d.status == "ready" and d.file_hash}

    view = ExplorerView()
    for d in docs:
        # Per-user view of the provenance: "" when the ACL hides it.
        visible_path = d.original_path if d.id in allowed else ""
        label = labels.get(d.batch_id or "", NO_BATCH_LABEL)
        # Explorer root: the network folder the upload came from when we can
        # see it, otherwise the batch label — so a restricted document still
        # sits in a folder tree, just not one that names the share.
        root = upload_root(visible_path, d.source_path) or label
        # Roots this document contributes for ANY caller (ACL ignored).
        network = upload_root(d.original_path, d.source_path)
        view.derived_roots.update({network, label} - {""})
        view.visible_roots.add(root)
        view.rows.append(
            DocumentSchema(
                id=d.id,
                # Display name = the upload-relative path (nicer than batch_id/...).
                filename=d.source_path if d.source_path else d.filename,
                file_type=d.file_type,
                upload_date=d.upload_date.isoformat(),
                page_count=d.page_count,
                chunk_count=d.chunk_count,
                status=d.status,
                stage=d.stage,
                uploaded_by=d.uploaded_by,
                original_path=visible_path,
                version=d.version,
                upload_root=root,
                folder_path=folder_path(d.source_path),
                duplicate_of=ready_by_hash.get(d.file_hash, "") if d.status == "skipped_duplicate" else "",
            )
        )
    return view


def layout_for(view: ExplorerView, folders, placements) -> LayoutResponse:
    """The shared layout, cut down to the roots this caller may see."""
    return LayoutResponse(
        folders=[
            LayoutFolderSchema(root=f.root, folder_path=f.folder_path, created_by=f.created_by)
            for f in folders
            if view.serves(f.root)
        ],
        placements=[
            LayoutPlacementSchema(document_id=p.document_id, root=p.root, folder_path=p.folder_path)
            for p in placements
            if view.serves(p.root)
        ],
    )
