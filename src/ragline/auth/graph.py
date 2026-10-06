"""Microsoft Graph client-credentials calls — group membership only.

Primary group source is the ID token's groups claim, cached at login and
refreshed by session re-validation (auth/revalidate.py). This module covers
what those cannot: the >200-group overage (Entra omits the claim entirely)
and TTL refresh between re-validations. Both need the app registration's
GroupMember.Read.All application permission — which the RUNBOOK says NOT to
grant unless overage users actually exist. Without it these calls fail and
the fail-closed polarity below applies; nothing else in the app breaks.

Failure polarity: a user whose cache cannot be refreshed and has expired gets
NO groups — they still match documents readable by "all authenticated users"
and by their own oid, nothing else. Graph being down never widens access.
"""

import time
from datetime import datetime, timedelta, timezone

import httpx
import structlog

from ragline.auth.dependencies import AuthedUser
from ragline.config import settings
from ragline.storage.auth_models import get_user, set_user_groups

log = structlog.get_logger()

_GRAPH = "https://graph.microsoft.com/v1.0"

# App-only token cache: (access_token, unix_expiry).
_token_cache: tuple[str, float] | None = None


async def _app_token() -> str:
    global _token_cache
    if _token_cache and _token_cache[1] - time.time() > 60:
        return _token_cache[0]
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            f"https://login.microsoftonline.com/{settings.entra_tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": settings.entra_client_id,
                "client_secret": settings.entra_client_secret,
                "grant_type": "client_credentials",
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        res.raise_for_status()
        payload = res.json()
    _token_cache = (payload["access_token"], time.time() + int(payload.get("expires_in", 300)))
    return _token_cache[0]


async def fetch_member_groups(oid: str) -> list[str]:
    """All security-enabled groups (transitive) for one user, via Graph."""
    token = await _app_token()
    groups: list[str] = []
    url = f"{_GRAPH}/users/{oid}/getMemberObjects"
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"securityEnabledOnly": True},
        )
        res.raise_for_status()
        payload = res.json()
        groups.extend(str(g) for g in payload.get("value", []))
    return groups


def _is_fresh(refreshed_at: datetime | None) -> bool:
    if refreshed_at is None:
        return False
    if refreshed_at.tzinfo is None:
        refreshed_at = refreshed_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - refreshed_at < timedelta(
        hours=settings.groups_cache_ttl_hours
    )


async def effective_groups(user: AuthedUser) -> list[str]:
    """The group ids the ACL check should use for this user, freshness-aware.

    Reads the DB row (not just the middleware snapshot) for refreshed_at,
    refreshes via Graph when the cache is missing/stale/overage, and falls
    back per the polarity note above.
    """
    row = await get_user(user.oid)
    if row is None:
        # No row (e.g. dev identity) — only the token-borne groups apply.
        return user.groups

    if _is_fresh(row.groups_refreshed_at) and not (row.groups_overage and not row.groups):
        return row.groups

    try:
        groups = await fetch_member_groups(user.oid)
        await set_user_groups(user.oid, groups)
        return groups
    except Exception as e:
        log.warning("graph group refresh failed", oid=user.oid, error=str(e))
        # Stale-but-present cache is only honoured while within TTL — which
        # it is not here — so: no groups. Own-oid and all-authenticated
        # matches still work; access never widens on an outage.
        return row.groups if _is_fresh(row.groups_refreshed_at) else []
