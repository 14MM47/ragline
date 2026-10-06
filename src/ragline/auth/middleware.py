"""Auth middleware — pure ASGI, deliberately NOT BaseHTTPMiddleware.

BaseHTTPMiddleware wraps the response in its own streaming machinery, which
has a history of buffering/cancellation bugs around long-lived SSE responses —
and /api/chat streaming is the product's core UX. A raw ASGI callable touches
only the request path: resolve cookie -> attach user -> pass through untouched.

Everything is behind auth except the allowlist below. Unauthenticated API
calls get 401 JSON (the SPA redirects on it); unauthenticated navigations get
302 to the login flow, so hitting the bare URL in a browser "just works".

Two extra gates ride here because this is the one place every request passes:

* Origin check (CSRF): SameSite=Lax treats every host under the corporate
  registrable domain as "same site", so a compromised sibling intranet app
  could forge requests with the cookie attached. Browsers stamp an Origin
  header on cross-origin (and all non-GET) requests. Two consequences here:
  a state-changing request with a foreign Origin is REJECTED (403), and any
  foreign-Origin request (GET included) is treated as ANONYMOUS — never
  resolving the session — so it cannot drive session bookkeeping side effects
  (last_seen keepalive, re-validation) even on allowlisted GETs. Requests
  without an Origin (curl/scripts, same-origin GETs) are unaffected.

* Non-HTTP scopes are refused outright. No websocket routes exist; if one
  ever appears it must NOT ship unauthenticated by default because this
  middleware only understood http.
"""

from http.cookies import SimpleCookie
from urllib.parse import urlsplit

import structlog
from starlette.responses import JSONResponse, RedirectResponse

from ragline.auth.dependencies import AuthedUser
from ragline.auth.sessions import COOKIE_NAME, unsign_session_id
from ragline.config import settings

log = structlog.get_logger()

# Paths reachable without a session: the login dance itself and the health
# probe (monitoring runs unauthenticated; health.py serves a bare liveness
# body to anonymous callers and detail only to signed-in users).
_ALLOW_PREFIXES = ("/api/auth/",)
_ALLOW_EXACT = ("/api/health",)

_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


def _session_id_from_scope(scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            cookie = SimpleCookie()
            try:
                cookie.load(value.decode("latin-1"))
            except Exception:
                return None
            morsel = cookie.get(COOKIE_NAME)
            if morsel is None:
                return None
            return unsign_session_id(morsel.value)
    return None


def _header(scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


def _origin_is_foreign(scope) -> bool:
    """True when an Origin header is present and its (scheme, netloc) is not
    APP_BASE_URL's. False when absent (non-browser client, or a same-origin
    GET — browsers omit Origin there) or when no base URL is configured
    (dev/tests). "Origin: null" parses to empty scheme/netloc and counts as
    foreign — it is attacker-reachable, never us."""
    expected = settings.app_base_url.rstrip("/").lower()
    if not expected:
        return False
    origin = _header(scope, b"origin")
    if not origin:
        return False
    parts = urlsplit(origin.lower())
    expected_parts = urlsplit(expected)
    return (parts.scheme, parts.netloc) != (expected_parts.scheme, expected_parts.netloc)


def _origin_mismatch(scope) -> bool:
    """True when a state-changing request carries a foreign Origin."""
    return scope.get("method", "GET") in _STATE_CHANGING and _origin_is_foreign(scope)


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan" or not settings.auth_enabled:
            return await self.app(scope, receive, send)

        if scope["type"] != "http":
            # Websocket (or anything else): refuse — nothing here is
            # authenticated for non-http scopes, so nothing may serve them.
            if scope["type"] == "websocket":
                await receive()  # consume websocket.connect
                await send({"type": "websocket.close", "code": 1008})
            return

        path = scope.get("path", "")
        allowlisted = path in _ALLOW_EXACT or path.startswith(_ALLOW_PREFIXES)

        # CSRF gate before anything else — applies to allowlisted paths too
        # (POST /api/auth/logout is exactly the kind of thing to protect).
        if _origin_mismatch(scope):
            log.warning("cross-origin state-changing request rejected",
                        path=path, origin=_header(scope, b"origin"))
            response = JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
            return await response(scope, receive, send)

        # Resolve the session whenever a cookie is present — even allowlisted
        # routes (/api/auth/me) want the user attached; for them the allowlist
        # only means "never block".
        #
        # BUT never resolve for a foreign Origin: a same-site sibling host
        # (same-site to the cookie under Lax) could otherwise fire credentialed
        # GETs whose only effect is server-side bookkeeping — resolve_session's
        # last_seen touch (defeating idle timeout) and triggering re-validation
        # (amplifying the single-flight path). Those requests can't read the
        # response cross-origin anyway; treating them as anonymous removes the
        # side effect. Same-origin GETs send no Origin and are unaffected.
        session_id = _session_id_from_scope(scope)
        authenticated = False
        if session_id and not _origin_is_foreign(scope):
            # Import here so the module can be imported before the DB exists.
            from ragline.storage.auth_models import resolve_session

            resolved = await resolve_session(session_id)
            if resolved is not None:
                row, user = resolved
                # Periodic silent re-validation against Entra: bounds the lag
                # between "account disabled in Entra" and "session dead here".
                from ragline.auth.revalidate import ensure_session_validated

                if await ensure_session_validated(row):
                    scope.setdefault("state", {})["user"] = AuthedUser(
                        oid=user.oid,
                        upn=user.upn,
                        display_name=user.display_name,
                        groups=user.groups,
                        groups_overage=user.groups_overage,
                        session_id=row.id,
                    )
                    authenticated = True

        if authenticated or allowlisted:
            return await self.app(scope, receive, send)

        # Unauthenticated. APIs get JSON; navigations get sent to sign in.
        if path.startswith("/api/"):
            response = JSONResponse({"detail": "Not authenticated"}, status_code=401)
        else:
            response = RedirectResponse("/api/auth/login", status_code=302)
        return await response(scope, receive, send)
