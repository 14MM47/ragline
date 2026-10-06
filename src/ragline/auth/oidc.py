"""OIDC login flow against Entra ID — the only place tokens are handled.

Backend-for-frontend: the server runs the authorization-code + PKCE flow and
the browser ends up with nothing but ragline's own opaque session cookie. The
ID token is validated (signature via tenant JWKS, issuer, audience, nonce) by
authlib inside authorize_access_token(), consumed for its claims, and never
stored or re-issued. The refresh token (offline_access) IS stored — Fernet-
encrypted on the session row — solely so auth/revalidate.py can re-check the
account against Entra on a timer.

Groups arrive in the ID token's groups claim (app registration: "Security
groups as Group IDs in the ID token"). Tenants emit an overage marker instead
when a user is in >200 groups — we record that and leave the cached groups for
the Graph fallback (auth/graph.py) to refresh; the ACL layer fails closed on
an empty cache, never open.
"""

import structlog
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Request
from starlette.responses import JSONResponse, RedirectResponse

from ragline.auth.dependencies import AuthedUser, get_current_user
from ragline.auth.sessions import (
    clear_session_cookie,
    encrypt_refresh_token,
    set_session_cookie,
)
from ragline.config import settings
from ragline.storage.auth_models import create_app_session, delete_app_session, upsert_user

log = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

_oauth = OAuth()


def _client():
    """Register the Entra client lazily so import order and tests stay simple."""
    if _oauth.create_client("entra") is None:
        _oauth.register(
            "entra",
            client_id=settings.entra_client_id,
            client_secret=settings.entra_client_secret,
            server_metadata_url=(
                f"https://login.microsoftonline.com/{settings.entra_tenant_id}"
                "/v2.0/.well-known/openid-configuration"
            ),
            client_kwargs={
                # offline_access: Entra returns a refresh token, used ONLY for
                # silent session re-validation (auth/revalidate.py) — bounds
                # revocation lag to SESSION_REVALIDATE_MINUTES.
                "scope": "openid profile email offline_access",
                "code_challenge_method": "S256",  # PKCE
            },
        )
    return _oauth.entra


def _redirect_uri() -> str:
    base = settings.app_base_url.rstrip("/")
    return f"{base}/api/auth/callback"


@router.get("/login")
async def login(request: Request):
    """Send the browser to Entra. State + nonce live in the (signed) login cookie."""
    return await _client().authorize_redirect(request, _redirect_uri())


@router.get("/callback")
async def callback(request: Request):
    """Code exchange + ID-token validation, then mint ragline's own session."""
    try:
        token = await _client().authorize_access_token(request)
    except OAuthError as e:
        log.warning("oidc callback failed", error=str(e))
        return JSONResponse({"detail": f"Sign-in failed: {e.error}"}, status_code=401)

    claims = token.get("userinfo") or {}
    oid = claims.get("oid")
    if not oid:
        # A v2.0 Entra ID token always carries oid; its absence means the
        # token is not what we expect — refuse rather than guess.
        log.warning("id token missing oid claim", claims=list(claims.keys()))
        return JSONResponse({"detail": "Sign-in failed: no oid claim"}, status_code=401)

    # Group ids from the token, or the >200-group overage marker.
    claim_names = claims.get("_claim_names") or {}
    overage = "groups" in claim_names
    raw_groups = claims.get("groups")
    groups = [str(g) for g in raw_groups] if isinstance(raw_groups, list) else None

    user = await upsert_user(
        oid=str(oid),
        upn=str(claims.get("preferred_username", "")),
        display_name=str(claims.get("name", "")),
        groups=groups,
        groups_overage=overage,
    )
    # The refresh token (offline_access) powers silent re-validation; stored
    # Fernet-encrypted, never sent to the browser. Its absence is tolerated
    # here but the session will fail closed at the first re-validation.
    refresh_token = str(token.get("refresh_token") or "")
    if not refresh_token:
        log.warning("no refresh token in callback — check offline_access consent",
                    oid=str(oid))
    row = await create_app_session(user.oid, refresh_token_enc=encrypt_refresh_token(refresh_token))
    log.info("user signed in", oid=user.oid, upn=user.upn, groups_overage=overage)

    response = RedirectResponse("/", status_code=302)
    set_session_cookie(response, row.id)
    return response


@router.post("/logout")
async def logout(request: Request):
    """Kill the ragline session; POST-only so a cross-site link/img can't
    CSRF users out (and the Origin gate covers forged POSTs).

    Returns where the SPA should navigate next: "/" by default (the Entra
    browser session survives — personal devices), or the Entra end-session
    URL when LOGOUT_FROM_ENTRA=true (shared/kiosk machines, where a silent
    SSO round-trip would sign the NEXT person in as the previous user).
    """
    user = getattr(request.state, "user", None)
    if user is not None and user.session_id:
        await delete_app_session(user.session_id)
        log.info("user signed out", oid=user.oid)

    logout_url = "/"
    if settings.logout_from_entra:
        from urllib.parse import quote

        post_logout = quote(settings.app_base_url.rstrip("/") or "/", safe="")
        logout_url = (
            f"https://login.microsoftonline.com/{settings.entra_tenant_id}"
            f"/oauth2/v2.0/logout?post_logout_redirect_uri={post_logout}"
        )
    response = JSONResponse({"logout_url": logout_url})
    clear_session_cookie(response)
    return response


@router.get("/me")
async def me(request: Request):
    """Identity for the UI header. 401 (from get_current_user) when signed out."""
    user: AuthedUser = get_current_user(request)
    return {
        "oid": user.oid,
        "upn": user.upn,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
        "auth_enabled": settings.auth_enabled,
    }
