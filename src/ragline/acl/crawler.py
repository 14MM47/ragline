"""The ACL crawler — one pass over every document's original_path.

Runs as a SEPARATE PROCESS (scripts/acl_crawl.py under a systemd timer),
never inside the app: SMB round-trips for thousands of files must not share
an event loop with user requests, and a crashed crawl must not take chat
down. Cross-process SQLite safety comes from WAL + busy_timeout (metadata_db)
and this process committing one small transaction per document.

Per-document outcomes map to DocumentAcl.crawl_status; on any failure the
previous principals survive until ACL_STALE_DAYS expires them (the upsert
implements that policy, not this loop).
"""

import asyncio
from dataclasses import dataclass, field

import structlog

from ragline.acl.paths import canonicalize_unc
from ragline.acl.smb import evaluate_dacl, fetch_security_descriptor
from ragline.config import settings
from ragline.storage.acl_models import upsert_document_acl
from ragline.storage.metadata_db import get_all_ready_documents

log = structlog.get_logger()


@dataclass
class CrawlStats:
    ok: int = 0
    blank_path: int = 0
    unreachable: int = 0
    access_denied: int = 0
    parse_error: int = 0
    unresolved_sids: set[str] = field(default_factory=set)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "blank_path": self.blank_path,
            "unreachable": self.unreachable,
            "access_denied": self.access_denied,
            "parse_error": self.parse_error,
            "unresolved_sid_count": len(self.unresolved_sids),
        }


def _classify_smb_error(exc: Exception) -> str:
    """Map an SMB exception onto a crawl_status, defaulting to unreachable."""
    text = f"{type(exc).__name__}: {exc}".lower()
    if "access" in text and "denied" in text:
        return "access_denied"
    return "unreachable"


async def crawl_all(concurrency: int = 8) -> CrawlStats:
    """Crawl every ready document once. Returns aggregate stats."""
    if not settings.smb_username or not settings.smb_password:
        raise RuntimeError("SMB_USERNAME / SMB_PASSWORD not configured — refusing to crawl")

    documents = await get_all_ready_documents()
    stats = CrawlStats()
    semaphore = asyncio.Semaphore(concurrency)

    async def crawl_one(doc) -> None:
        canonical = canonicalize_unc(doc.original_path)
        if canonical is None:
            stats.blank_path += 1
            await upsert_document_acl(
                doc.id, "", "blank_path",
                error_detail="original_path empty or not a UNC path",
            )
            return
        try:
            # smbprotocol is synchronous — run each fetch on a worker thread
            # so the semaphore actually yields concurrency.
            sd = await asyncio.to_thread(
                fetch_security_descriptor, canonical, settings.smb_username, settings.smb_password
            )
        except Exception as e:
            status = _classify_smb_error(e)
            setattr(stats, status, getattr(stats, status) + 1)
            await upsert_document_acl(doc.id, canonical, status, error_detail=str(e)[:500])
            return
        try:
            result = evaluate_dacl(sd)
        except Exception as e:
            stats.parse_error += 1
            await upsert_document_acl(doc.id, canonical, "parse_error", error_detail=str(e)[:500])
            return
        stats.ok += 1
        stats.unresolved_sids.update(result.unresolved_sids)
        await upsert_document_acl(
            doc.id,
            canonical,
            "ok",
            allow_all_authenticated=result.allow_all_authenticated,
            principals=result.principals,
            denied=result.denied,
        )

    async def bounded(doc):
        async with semaphore:
            await crawl_one(doc)

    await asyncio.gather(*(bounded(d) for d in documents))
    log.info("acl crawl finished", **stats.as_dict())
    if stats.unresolved_sids:
        # Surfaced (capped) so unexpected SID populations are investigated,
        # not silently dropped — they can only ever deny, but a corpus full
        # of them means the cloud-SID assumption needs revisiting.
        log.warning("unresolved SIDs ignored (fail closed)",
                    sample=sorted(stats.unresolved_sids)[:10])
    return stats
