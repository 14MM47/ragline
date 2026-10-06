"""Admin surfaces — currently just ACL crawl health.

Everything here sits behind require_admin (membership of
ENTRA_ADMIN_GROUP_ID). The acl-status view exists because original_path is
free text and the crawler fails closed: a chunk of the corpus showing locked
citations reads as a bug to users, and this is where an admin sees exactly
which documents are failing and why (blank path, unreachable share, denied
READ_CONTROL, stale crawl) without shelling into the VM.
"""

import structlog
from fastapi import APIRouter, Depends

from ragline.auth.dependencies import AuthedUser, require_admin
from ragline.storage.acl_models import get_acl_status_summary

log = structlog.get_logger()

router = APIRouter(tags=["admin"])


@router.get("/admin/acl-status")
async def acl_status(user: AuthedUser = Depends(require_admin)):
    """Counts per crawl_status, last crawl time, and the failing documents."""
    return await get_acl_status_summary()


@router.post("/admin/users/{oid}/revoke-sessions")
async def revoke_user_sessions(oid: str, user: AuthedUser = Depends(require_admin)):
    """Kill every live session for one user, immediately.

    The incident/offboarding lever: disabling the account in Entra alone
    leaves existing sessions alive until the next silent re-validation
    (SESSION_REVALIDATE_MINUTES); this closes them NOW. Takes the Entra
    object id (shown in the portal on the user's page).
    """
    from ragline.storage.auth_models import delete_sessions_for_user

    count = await delete_sessions_for_user(oid)
    log.info("admin revoked sessions", target_oid=oid, by=user.oid, count=count)
    return {"revoked": count, "oid": oid}
