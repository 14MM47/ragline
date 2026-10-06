"""Auth middleware — the allowlist matrix and session resolution.

The middleware is the enforcement boundary for the whole app, so the matrix
matters more than any single case: allowlisted paths pass without a cookie,
API paths 401 as JSON, navigations 302 into the login flow, a valid signed
cookie attaches the user, and tampered/unknown/expired cookies are all
equivalent to no cookie at all (fail closed).
"""

from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import ragline.storage.auth_models as auth_models
from ragline.auth.dependencies import AuthedUser, get_current_user
from ragline.auth.middleware import AuthMiddleware
from ragline.auth.sessions import COOKIE_NAME, sign_session_id
from ragline.config import settings


class _UserRow:
    oid = "11111111-2222-3333-4444-555555555555"
    upn = "alice@corp.example"
    display_name = "Alice"
    groups = ["g-eng"]
    groups_overage = False


class _SessionRow:
    id = "session-abc"
    user_oid = _UserRow.oid
    # Freshly validated: ensure_session_validated is a no-op (no network) —
    # which is itself the behaviour these tests rely on staying true.
    validated_at = datetime.now(timezone.utc)
    refresh_token_enc = ""


@pytest.fixture
def client(monkeypatch):
    settings.auth_enabled = True

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/api/auth/login")
    async def login():
        return {"page": "login"}

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/whoami")
    async def whoami(user: AuthedUser = Depends(get_current_user)):
        return {"oid": user.oid, "upn": user.upn}

    @app.post("/api/echo")
    async def echo(user: AuthedUser = Depends(get_current_user)):
        return {"ok": True}

    @app.get("/")
    async def index():
        return {"page": "spa"}

    async def fake_resolve(session_id):
        if session_id == "session-abc":
            return _SessionRow(), _UserRow()
        return None

    monkeypatch.setattr(auth_models, "resolve_session", fake_resolve)
    return TestClient(app)


def _cookie(value: str) -> dict:
    return {COOKIE_NAME: value}


def test_health_passes_without_cookie(client):
    assert client.get("/api/health").status_code == 200


def test_auth_routes_pass_without_cookie(client):
    assert client.get("/api/auth/login").status_code == 200


def test_api_without_cookie_is_401_json(client):
    res = client.get("/api/whoami")
    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}


def test_navigation_without_cookie_redirects_to_login(client):
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/api/auth/login"


def test_valid_cookie_attaches_user(client):
    res = client.get("/api/whoami", cookies=_cookie(sign_session_id("session-abc")))
    assert res.status_code == 200
    assert res.json() == {"oid": _UserRow.oid, "upn": _UserRow.upn}


def test_unknown_session_is_rejected(client):
    res = client.get("/api/whoami", cookies=_cookie(sign_session_id("session-gone")))
    assert res.status_code == 401


def test_tampered_cookie_is_rejected(client):
    # A raw (unsigned) session id must not be accepted even if it exists.
    res = client.get("/api/whoami", cookies=_cookie("session-abc"))
    assert res.status_code == 401


def test_auth_disabled_passes_everything(client):
    settings.auth_enabled = False
    assert client.get("/api/whoami").status_code == 200  # dev identity
    assert client.get("/", follow_redirects=False).status_code == 200


# --- Origin check (CSRF: sibling intranet hosts are "same-site" to cookies) --


@pytest.fixture
def origin_client(client, monkeypatch):
    monkeypatch.setattr(settings, "app_base_url", "https://ragline.corp.example")
    return client


def _auth_cookie() -> dict:
    return _cookie(sign_session_id("session-abc"))


def test_cross_origin_post_is_rejected(origin_client):
    res = origin_client.post(
        "/api/echo",
        cookies=_auth_cookie(),
        headers={"Origin": "https://evil.corp.example"},
    )
    assert res.status_code == 403


def test_null_origin_post_is_rejected(origin_client):
    res = origin_client.post("/api/echo", cookies=_auth_cookie(), headers={"Origin": "null"})
    assert res.status_code == 403


def test_same_origin_post_passes(origin_client):
    res = origin_client.post(
        "/api/echo",
        cookies=_auth_cookie(),
        headers={"Origin": "https://ragline.corp.example"},
    )
    assert res.status_code == 200


def test_post_without_origin_passes(origin_client):
    # curl/scripts send no Origin; they are not a CSRF vector.
    assert origin_client.post("/api/echo", cookies=_auth_cookie()).status_code == 200


def test_cross_origin_get_is_anonymized(origin_client):
    # A credentialed GET from a foreign origin (sibling intranet host) must be
    # treated as anonymous — the session is not resolved, so it can't drive
    # last_seen keepalive / re-validation. get_current_user then 401s.
    res = origin_client.get(
        "/api/whoami",
        cookies=_auth_cookie(),
        headers={"Origin": "https://evil.corp.example"},
    )
    assert res.status_code == 401


def test_same_origin_get_still_authenticates(origin_client):
    res = origin_client.get(
        "/api/whoami",
        cookies=_auth_cookie(),
        headers={"Origin": "https://ragline.corp.example"},
    )
    assert res.status_code == 200


def test_no_origin_get_authenticates(origin_client):
    # Same-origin GETs (and non-browser clients) send no Origin — unaffected.
    assert origin_client.get("/api/whoami", cookies=_auth_cookie()).status_code == 200


# --- non-HTTP scopes ---------------------------------------------------------


def test_websocket_is_refused(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws"):
            pass
    assert exc.value.code == 1008
