"""Auth tables — Entra-backed users and server-side sessions.

The browser holds only an opaque, signed session id; everything about the
user — identity, group memberships from the ID token, expiry — lives in these
rows. A User row is upserted at every successful Entra sign-in, so the app
never accumulates stale identity data beyond the last login.

groups_json caches the group object IDs from the ID token's groups claim.
When the tenant emits an overage marker instead (>200 groups), groups_overage
is set and the Graph fallback fills the cache. The ACL access check
treats an expired cache as "no groups" — fail closed, never fail open.
"""

import json
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlmodel import Field, SQLModel

from ragline.config import settings


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    """One Entra principal that has signed in at least once."""

    __tablename__ = "auth_user"

    oid: str = Field(primary_key=True)               # Entra object id (GUID)
    upn: str = ""                                    # preferred_username claim
    display_name: str = ""                           # name claim
    groups_json: str = "[]"                          # group object ids from the token
    groups_overage: bool = False                     # token had >200 groups; cache via Graph
    groups_refreshed_at: datetime | None = None      # when groups_json was last filled
    last_login: datetime = Field(default_factory=_utcnow)
    created_at: datetime = Field(default_factory=_utcnow)

    @property
    def groups(self) -> list[str]:
        try:
            return json.loads(self.groups_json)
        except Exception:
            return []


class AppSession(SQLModel, table=True):
    """One browser session. The cookie carries only this row's random id."""

    __tablename__ = "auth_session"

    id: str = Field(default_factory=lambda: secrets.token_urlsafe(32), primary_key=True)
    user_oid: str = Field(foreign_key="auth_user.oid", index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    last_seen_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime = Field(
        default_factory=lambda: _utcnow() + timedelta(days=settings.session_absolute_days)
    )
    # Entra refresh token, Fernet-encrypted at rest (auth/sessions.py). Used
    # ONLY to silently re-validate the session against Entra — a disabled or
    # revoked account fails the refresh grant and the session dies within
    # SESSION_REVALIDATE_MINUTES instead of surviving to expiry.
    refresh_token_enc: str = ""
    # When Entra last confirmed this session's account is alive.
    validated_at: datetime = Field(default_factory=_utcnow)


# Imported lazily so this module can be imported by init_db without cycles.
def _session_factory():
    from ragline.storage.metadata_db import _async_session

    return _async_session


async def upsert_user(
    oid: str,
    upn: str,
    display_name: str,
    groups: list[str] | None,
    groups_overage: bool,
) -> User:
    """Create or refresh the User row for a successful sign-in.

    groups=None means "the token carried no usable claim" (overage or claim
    not configured) — the existing cache is left in place for the Graph
    fallback to refresh, rather than being wiped to [].
    """
    async with _session_factory()() as session:
        user = (await session.execute(select(User).where(User.oid == oid))).scalar_one_or_none()
        now = _utcnow()
        if user is None:
            user = User(oid=oid)
        user.upn = upn
        user.display_name = display_name
        user.groups_overage = groups_overage
        user.last_login = now
        if groups is not None:
            user.groups_json = json.dumps(groups)
            user.groups_refreshed_at = now
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def get_user(oid: str) -> User | None:
    async with _session_factory()() as session:
        return (await session.execute(select(User).where(User.oid == oid))).scalar_one_or_none()


async def set_user_groups(oid: str, groups: list[str]) -> None:
    """Refresh the cached group memberships (Graph overage fallback / TTL)."""
    async with _session_factory()() as session:
        user = (await session.execute(select(User).where(User.oid == oid))).scalar_one_or_none()
        if user is None:
            return
        user.groups_json = json.dumps(groups)
        user.groups_refreshed_at = _utcnow()
        session.add(user)
        await session.commit()


async def create_app_session(user_oid: str, refresh_token_enc: str = "") -> AppSession:
    async with _session_factory()() as session:
        row = AppSession(user_oid=user_oid, refresh_token_enc=refresh_token_enc)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def get_app_session(session_id: str) -> AppSession | None:
    """Plain session read — NO last_seen touch or expiry side-effects.

    Used by the single-flight re-validation re-read (auth/revalidate.py): it
    needs the current validated_at/refresh_token_enc under the lock without
    resolve_session's throttled last_seen write or expiry deletion.
    """
    async with _session_factory()() as session:
        return (
            await session.execute(select(AppSession).where(AppSession.id == session_id))
        ).scalar_one_or_none()


async def mark_session_validated(session_id: str, refresh_token_enc: str | None = None) -> None:
    """Record a successful Entra re-validation (and the rotated refresh token,
    when Entra issued one — it usually does)."""
    async with _session_factory()() as session:
        row = (
            await session.execute(select(AppSession).where(AppSession.id == session_id))
        ).scalar_one_or_none()
        if row is None:
            return
        row.validated_at = _utcnow()
        if refresh_token_enc is not None:
            row.refresh_token_enc = refresh_token_enc
        session.add(row)
        await session.commit()


# last_seen_at is written at most this often — a per-request UPDATE would
# double the DB writes of every API call for no security benefit.
_TOUCH_INTERVAL = timedelta(minutes=5)


async def resolve_session(session_id: str) -> tuple[AppSession, User] | None:
    """Session id -> (session, user), enforcing idle + absolute expiry.

    Expired rows are deleted on sight so the table self-cleans under use
    (a scheduled purge still handles sessions that simply never return).
    """
    async with _session_factory()() as session:
        row = (
            await session.execute(select(AppSession).where(AppSession.id == session_id))
        ).scalar_one_or_none()
        if row is None:
            return None
        now = _utcnow()

        def _aware(dt: datetime) -> datetime:
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

        last_seen = _aware(row.last_seen_at)
        expires = _aware(row.expires_at)
        if now > expires or now - last_seen > timedelta(hours=settings.session_idle_hours):
            await session.delete(row)
            await session.commit()
            return None
        if now - last_seen > _TOUCH_INTERVAL:
            row.last_seen_at = now
            session.add(row)
            await session.commit()
        user = (
            await session.execute(select(User).where(User.oid == row.user_oid))
        ).scalar_one_or_none()
        if user is None:
            return None
        return row, user


async def delete_app_session(session_id: str) -> None:
    async with _session_factory()() as session:
        await session.execute(delete(AppSession).where(AppSession.id == session_id))
        await session.commit()


async def delete_sessions_for_user(user_oid: str) -> int:
    """Revoke every session for one user (offboarding / forced sign-out).
    Returns the number of sessions killed."""
    async with _session_factory()() as session:
        result = await session.execute(
            delete(AppSession).where(AppSession.user_oid == user_oid)
        )
        await session.commit()
        return result.rowcount or 0


async def purge_expired_sessions() -> int:
    """Delete sessions past their absolute expiry; returns rows removed."""
    async with _session_factory()() as session:
        result = await session.execute(
            delete(AppSession).where(AppSession.expires_at < _utcnow())
        )
        await session.commit()
        return result.rowcount or 0
