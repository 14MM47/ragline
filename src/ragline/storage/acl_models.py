"""DocumentAcl — the crawled NTFS permissions for each ingested document.

One row per document, written by the ACL crawler (a separate process on a
systemd timer) and read on every citation enrichment and /content download.
The row stores RESOLVED Entra principals (user and group object ids), not raw
SIDs — resolution happens once at crawl time (acl/sid_map.py).

Freshness is part of the security model: a row whose last successful crawl is
older than ACL_STALE_DAYS no longer grants anything, so a crawler that dies
quietly degrades to "nobody can open citations" (loud, safe) rather than
"everyone keeps yesterday's access forever" (silent, unsafe).
"""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlmodel import Field, SQLModel

from ragline.config import settings

# crawl_status values (kept as plain strings, matching the codebase style):
#   ok            — DACL read and resolved; principals_json is authoritative
#   blank_path    — original_path empty or not a parseable UNC path
#   unreachable   — share/host not reachable at crawl time
#   access_denied — service account lacks READ_CONTROL on the file
#   parse_error   — security descriptor bytes could not be parsed


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocumentAcl(SQLModel, table=True):
    __tablename__ = "document_acl"

    document_id: str = Field(primary_key=True, foreign_key="document.id")
    normalized_path: str = Field(default="", index=True)
    # True when a well-known "everyone" SID grants read (Everyone,
    # Authenticated Users, BUILTIN\Users).
    allow_all_authenticated: bool = False
    # Entra object ids (users AND groups) holding read. JSON list, same
    # pattern as User.groups_json.
    principals_json: str = "[]"
    # Entra object ids read-DENIED by an explicit deny ACE. Stored separately
    # because a deny beats an allow granted through a DIFFERENT principal
    # (user denied by name but allowed via group) — the access check
    # subtracts these against the user's oid + groups, mirroring Windows'
    # deny-first evaluation.
    denied_json: str = "[]"
    crawl_status: str = "blank_path"
    crawled_at: datetime = Field(default_factory=_utcnow)
    last_ok_at: datetime | None = None
    error_detail: str = ""

    @property
    def principals(self) -> list[str]:
        try:
            return json.loads(self.principals_json)
        except Exception:
            return []

    @property
    def denied(self) -> list[str]:
        try:
            return json.loads(self.denied_json)
        except Exception:
            return []

    @property
    def is_fresh(self) -> bool:
        """A row only grants access while its last SUCCESSFUL crawl is recent."""
        if self.last_ok_at is None:
            return False
        last_ok = (
            self.last_ok_at.replace(tzinfo=timezone.utc)
            if self.last_ok_at.tzinfo is None
            else self.last_ok_at
        )
        return _utcnow() - last_ok < timedelta(days=settings.acl_stale_days)


def _session_factory():
    from ragline.storage.metadata_db import _async_session

    return _async_session


async def upsert_document_acl(
    document_id: str,
    normalized_path: str,
    crawl_status: str,
    allow_all_authenticated: bool = False,
    principals: list[str] | None = None,
    denied: list[str] | None = None,
    error_detail: str = "",
) -> None:
    """Record one crawl result.

    On success ('ok') the principals replace the stored set and last_ok_at
    advances. On failure the previous principals are KEPT (they stay valid
    until staleness expires them) and only status/error/crawled_at move —
    a one-night network blip must not revoke the whole corpus by morning.
    """
    async with _session_factory()() as session:
        row = (
            await session.execute(select(DocumentAcl).where(DocumentAcl.document_id == document_id))
        ).scalar_one_or_none()
        now = _utcnow()
        if row is None:
            row = DocumentAcl(document_id=document_id)
        row.normalized_path = normalized_path
        row.crawl_status = crawl_status
        row.crawled_at = now
        row.error_detail = error_detail
        if crawl_status == "ok":
            row.allow_all_authenticated = allow_all_authenticated
            row.principals_json = json.dumps(sorted(principals or []))
            row.denied_json = json.dumps(sorted(denied or []))
            row.last_ok_at = now
        session.add(row)
        await session.commit()


async def get_acls_by_document_ids(document_ids: list[str]) -> dict[str, DocumentAcl]:
    """Bulk fetch for citation enrichment — one query per answer, not per source."""
    if not document_ids:
        return {}
    async with _session_factory()() as session:
        rows = (
            (await session.execute(select(DocumentAcl).where(DocumentAcl.document_id.in_(document_ids))))
            .scalars()
            .all()
        )
        return {row.document_id: row for row in rows}


async def get_acl_status_summary() -> dict:
    """Admin view: counts per crawl_status + the documents failing closed."""
    async with _session_factory()() as session:
        counts = dict(
            (
                await session.execute(
                    select(DocumentAcl.crawl_status, func.count()).group_by(DocumentAcl.crawl_status)
                )
            ).all()
        )
        last_crawl = (await session.execute(select(func.max(DocumentAcl.crawled_at)))).scalar()
        failing = (
            (
                await session.execute(
                    select(
                        DocumentAcl.document_id,
                        DocumentAcl.normalized_path,
                        DocumentAcl.crawl_status,
                        DocumentAcl.error_detail,
                    )
                    .where(DocumentAcl.crawl_status != "ok")
                    .limit(200)
                )
            )
            .all()
        )
        return {
            "counts": counts,
            "last_crawl_at": last_crawl.isoformat() if last_crawl else None,
            "failing": [
                {
                    "document_id": d,
                    "normalized_path": p,
                    "crawl_status": s,
                    "error_detail": e,
                }
                for d, p, s, e in failing
            ],
        }
