"""Silent session re-validation against Entra — bounds revocation lag.

Without this, "disable the account in Entra" only stops NEW logins; an
existing session survives to its own expiry (hours to days). Here, every
SESSION_REVALIDATE_MINUTES the middleware redeems the session's stored
refresh token against the tenant token endpoint. Entra checks account state
on every refresh grant, so a disabled account, revoked sessions ("Revoke
sign-in sessions" in the portal), or a Conditional Access change kills the
ragline session within one interval.

Outcome policy (matches the accepted outage trade-off from the design review):
  * refresh succeeds        -> validated_at advances, rotated token stored,
                               and the fresh ID token's groups claim updates
                               the group cache (so ACL changes ride along).
  * Entra says no (4xx)     -> the session is DELETED. Fail closed.
  * Entra unreachable (5xx/ -> the session is KEPT: an Entra outage must not
    network error)             sign the whole company out. A short cooldown
                               stops every request from re-dialing a dead
                               endpoint; revocation resumes when Entra does.
  * no refresh token stored -> DELETED (pre-migration session, offline_access
                               not consented, or SESSION_SECRET rotated) —
                               one visible re-login beats a silent hole.

The ID token in the refresh response is parsed WITHOUT signature validation:
it arrives on a direct TLS connection to login.microsoftonline.com in
exchange for our client secret, the same trust basis authlib's metadata
fetch already stands on. Only the groups/oid claims are read, never identity
we don't already have.
"""

import asyncio
import base64
import json
import time

import httpx
import structlog

from ragline.auth.sessions import decrypt_refresh_token, encrypt_refresh_token
from ragline.config import settings
from ragline.storage.auth_models import (
    AppSession,
    delete_app_session,
    get_app_session,
    mark_session_validated,
    set_user_groups,
)

log = structlog.get_logger()

# After a network/5xx failure, skip re-validation attempts for this long so an
# Entra outage costs one failed call per minute, not one per request.
_OUTAGE_COOLDOWN_S = 60.0
_outage_until = 0.0

# Per-session single-flight. Entra ROTATES the refresh token on redemption, so
# if concurrent requests for one session all crossed the freshness boundary and
# each redeemed the same stored token, the first would win and the rest would
# get invalid_grant — deleting a live session (spurious logout). The lock makes
# exactly one request redeem; the others re-read the just-written row and reuse
# it. Locks are created only for sessions that actually reach revalidation, and
# popped when the session is deleted, so the map stays bounded.
_session_locks: dict[str, asyncio.Lock] = {}


def _lock_for(session_id: str) -> asyncio.Lock:
    lock = _session_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[session_id] = lock
    return lock


async def _revoke(session_id: str) -> None:
    """Delete a session and drop its single-flight lock."""
    await delete_app_session(session_id)
    _session_locks.pop(session_id, None)


def _needs_validation(row: AppSession) -> bool:
    from datetime import datetime, timedelta, timezone

    validated = row.validated_at
    if validated is None:  # pre-migration row — treat as never validated
        return True
    if validated.tzinfo is None:
        validated = validated.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - validated
    return age > timedelta(minutes=settings.session_revalidate_minutes)


def _id_token_claims(id_token: str) -> dict:
    """Decode the JWT payload (no signature check — see module docstring)."""
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


async def ensure_session_validated(row: AppSession) -> bool:
    """True = session may be used; False = session was revoked (and deleted).

    Cheap no-op while validated_at is fresh — the token endpoint is only hit
    once per session per interval. Concurrent requests for one session are
    serialized (single-flight): only the first redeems the rotating refresh
    token; the rest re-read the freshly-written row and reuse the result.
    """
    global _outage_until

    # Fast path outside the lock: the overwhelming majority of requests are
    # within the freshness window and never touch Entra or the lock map.
    if not _needs_validation(row):
        return True

    async with _lock_for(row.id):
        # Re-read under the lock: a sibling request may have just validated
        # (or revoked) this session while we waited to acquire it.
        fresh = await get_app_session(row.id)
        if fresh is None:
            _session_locks.pop(row.id, None)
            return False  # deleted by the winner (revoked) — fail closed
        if not _needs_validation(fresh):
            return True  # someone else validated it — reuse, no second redeem
        if time.monotonic() < _outage_until:
            return True  # Entra known-down: keep sessions alive, retry later.

        refresh_token = decrypt_refresh_token(fresh.refresh_token_enc)
        if refresh_token is None:
            log.info("session has no usable refresh token — revoking", session_id=fresh.id[:8])
            await _revoke(fresh.id)
            return False

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.post(
                    f"https://login.microsoftonline.com/{settings.entra_tenant_id}"
                    "/oauth2/v2.0/token",
                    data={
                        "client_id": settings.entra_client_id,
                        "client_secret": settings.entra_client_secret,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "scope": "openid profile email offline_access",
                    },
                )
        except Exception as e:
            _outage_until = time.monotonic() + _OUTAGE_COOLDOWN_S
            log.warning("session re-validation skipped: token endpoint unreachable", error=str(e))
            return True

        if res.status_code >= 500:
            _outage_until = time.monotonic() + _OUTAGE_COOLDOWN_S
            log.warning("session re-validation skipped: token endpoint 5xx", status=res.status_code)
            return True

        if res.status_code != 200:
            # invalid_grant et al: Entra explicitly refused this account/session.
            detail = ""
            try:
                detail = res.json().get("error", "")
            except Exception:
                pass
            log.info("session revoked by Entra", user_oid=fresh.user_oid, error=detail)
            await _revoke(fresh.id)
            return False

        payload = res.json()
        new_refresh = payload.get("refresh_token", "")
        await mark_session_validated(
            fresh.id,
            refresh_token_enc=encrypt_refresh_token(new_refresh) if new_refresh else None,
        )

        # Fresh groups claim (if the tenant emits one) tightens ACL staleness
        # for free: group membership changes now land within the same interval.
        claims = _id_token_claims(payload.get("id_token", ""))
        groups = claims.get("groups")
        if isinstance(groups, list) and str(claims.get("oid", "")) == fresh.user_oid:
            await set_user_groups(fresh.user_oid, [str(g) for g in groups])

        return True
