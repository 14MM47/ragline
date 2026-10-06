"""Security-hardening behaviours: session re-validation against Entra,
refresh-token encryption at rest, POST-only logout, the admin session-kill
lever, the anonymous-health redaction, and file-based secrets.

The re-validation outcome policy is the part that matters most — each branch
maps to a security posture: 4xx = revoked (fail closed), 5xx/network = keep
(an Entra outage must not sign the company out), no token = revoked.
"""

import base64
import json
import types
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ragline.api.routes.health as health_module
import ragline.auth.revalidate as revalidate
import ragline.storage.auth_models as auth_models
from ragline.api.dependencies import get_vector_store
from ragline.api.routes import admin as admin_route
from ragline.auth import oidc as auth_oidc
from ragline.auth.dependencies import AuthedUser, require_admin
from ragline.auth.sessions import decrypt_refresh_token, encrypt_refresh_token
from ragline.config import settings

OID = "11111111-2222-3333-4444-555555555555"


# --- refresh-token encryption at rest ---------------------------------------


def test_refresh_token_encrypt_round_trip():
    stored = encrypt_refresh_token("0.ARoA-secret-refresh-token")
    assert stored != "0.ARoA-secret-refresh-token"  # never plaintext at rest
    assert decrypt_refresh_token(stored) == "0.ARoA-secret-refresh-token"


def test_refresh_token_empty_and_tampered():
    assert encrypt_refresh_token("") == ""
    assert decrypt_refresh_token("") is None
    assert decrypt_refresh_token("garbage") is None


def test_refresh_token_dies_with_rotated_secret():
    stored = encrypt_refresh_token("tok")
    settings.session_secret = "rotated"  # conftest restores this
    assert decrypt_refresh_token(stored) is None  # fail closed -> re-login


# --- session re-validation ---------------------------------------------------


class _Row:
    def __init__(self, validated_minutes_ago=999, refresh_token="rt-original"):
        self.id = "sess-1"
        self.user_oid = OID
        self.validated_at = datetime.now(timezone.utc) - timedelta(
            minutes=validated_minutes_ago
        )
        self.refresh_token_enc = (
            encrypt_refresh_token(refresh_token) if refresh_token else ""
        )


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _fake_httpx(monkeypatch, response=None, error=None):
    """Replace revalidate's httpx with a stub client returning `response`."""

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None):
            if error is not None:
                raise error
            _Client.last_data = data
            return response

    monkeypatch.setattr(revalidate, "httpx", types.SimpleNamespace(AsyncClient=_Client))
    return _Client


@pytest.fixture
def _reval(monkeypatch):
    """Common patches: no outage cooldown, isolated lock map, spy on DB writes,
    and a default under-lock re-read that echoes a still-stale row with a
    usable token (individual tests override get_app_session where needed)."""
    monkeypatch.setattr(revalidate, "_outage_until", 0.0)
    monkeypatch.setattr(revalidate, "_session_locks", {})
    calls = {"deleted": [], "validated": [], "groups": []}

    async def fake_delete(session_id):
        calls["deleted"].append(session_id)

    async def fake_mark(session_id, refresh_token_enc=None):
        calls["validated"].append((session_id, refresh_token_enc))

    async def fake_set_groups(oid, groups):
        calls["groups"].append((oid, groups))

    async def fake_get_app_session(session_id):
        # Still stale (forces the redemption path) and holds a usable token.
        return _Row(validated_minutes_ago=999, refresh_token="rt-original")

    monkeypatch.setattr(revalidate, "delete_app_session", fake_delete)
    monkeypatch.setattr(revalidate, "mark_session_validated", fake_mark)
    monkeypatch.setattr(revalidate, "set_user_groups", fake_set_groups)
    monkeypatch.setattr(revalidate, "get_app_session", fake_get_app_session)
    return calls


@pytest.mark.asyncio
async def test_fresh_session_skips_the_network(_reval, monkeypatch):
    _fake_httpx(monkeypatch, error=AssertionError("must not be called"))
    assert await revalidate.ensure_session_validated(_Row(validated_minutes_ago=1)) is True


@pytest.mark.asyncio
async def test_revoked_by_entra_deletes_session(_reval, monkeypatch):
    _fake_httpx(monkeypatch, _Resp(400, {"error": "invalid_grant"}))
    assert await revalidate.ensure_session_validated(_Row()) is False
    assert _reval["deleted"] == ["sess-1"]


@pytest.mark.asyncio
async def test_entra_outage_keeps_session(_reval, monkeypatch):
    _fake_httpx(monkeypatch, error=ConnectionError("dns down"))
    assert await revalidate.ensure_session_validated(_Row()) is True
    assert _reval["deleted"] == []
    # Cooldown armed: the next stale session doesn't re-dial the dead endpoint.
    _fake_httpx(monkeypatch, error=AssertionError("cooldown must skip the call"))
    assert await revalidate.ensure_session_validated(_Row()) is True


@pytest.mark.asyncio
async def test_entra_5xx_keeps_session(_reval, monkeypatch):
    _fake_httpx(monkeypatch, _Resp(503))
    assert await revalidate.ensure_session_validated(_Row()) is True
    assert _reval["deleted"] == []


@pytest.mark.asyncio
async def test_missing_refresh_token_fails_closed(_reval, monkeypatch):
    _fake_httpx(monkeypatch, error=AssertionError("must not be called"))

    async def no_token(session_id):
        return _Row(validated_minutes_ago=999, refresh_token="")

    monkeypatch.setattr(revalidate, "get_app_session", no_token)
    assert await revalidate.ensure_session_validated(_Row(refresh_token="")) is False
    assert _reval["deleted"] == ["sess-1"]


def _fake_id_token(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJSUzI1NiJ9.{payload}.sig"


@pytest.mark.asyncio
async def test_successful_revalidation_rotates_token_and_groups(_reval, monkeypatch):
    _fake_httpx(
        monkeypatch,
        _Resp(
            200,
            {
                "refresh_token": "rt-rotated",
                "id_token": _fake_id_token({"oid": OID, "groups": ["g-new"]}),
            },
        ),
    )
    assert await revalidate.ensure_session_validated(_Row()) is True
    [(session_id, new_enc)] = _reval["validated"]
    assert session_id == "sess-1"
    assert decrypt_refresh_token(new_enc) == "rt-rotated"  # rotated + encrypted
    assert _reval["groups"] == [(OID, ["g-new"])]
    assert _reval["deleted"] == []


@pytest.mark.asyncio
async def test_foreign_oid_in_id_token_never_updates_groups(_reval, monkeypatch):
    _fake_httpx(
        monkeypatch,
        _Resp(200, {"id_token": _fake_id_token({"oid": "someone-else", "groups": ["g"]})}),
    )
    assert await revalidate.ensure_session_validated(_Row()) is True
    assert _reval["groups"] == []


@pytest.mark.asyncio
async def test_concurrent_same_session_redeems_once(_reval, monkeypatch):
    """The single-flight lock: N parallel requests for one stale session must
    redeem the rotating token exactly ONCE — the losers reuse the freshly
    written row instead of double-spending it and self-revoking (the Fix 1
    race). Without the lock, the second+ redemptions would 400 and delete a
    live session.
    """
    monkeypatch.setattr(revalidate, "_outage_until", 0.0)
    _session_locks = {}
    monkeypatch.setattr(revalidate, "_session_locks", _session_locks)

    stale = _Row(validated_minutes_ago=999)
    calls = {"redeems": 0}

    # The DB row as the winner will rewrite it: after a successful redeem,
    # get_app_session must report it fresh so the losers short-circuit.
    state = {"validated": False}

    async def fake_get_app_session(session_id):
        r = _Row(validated_minutes_ago=0 if state["validated"] else 999)
        r.id = stale.id
        return r

    async def fake_mark(session_id, refresh_token_enc=None):
        state["validated"] = True

    monkeypatch.setattr(revalidate, "get_app_session", fake_get_app_session)
    monkeypatch.setattr(revalidate, "mark_session_validated", fake_mark)

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None):
            calls["redeems"] += 1
            # Only the FIRST redemption (with the original token) succeeds;
            # a second would arrive with a since-rotated token -> invalid_grant.
            if calls["redeems"] == 1:
                return _Resp(200, {"refresh_token": "rt-rotated", "id_token": ""})
            return _Resp(400, {"error": "invalid_grant"})

    monkeypatch.setattr(revalidate, "httpx", types.SimpleNamespace(AsyncClient=_Client))

    import asyncio

    results = await asyncio.gather(
        *[revalidate.ensure_session_validated(stale) for _ in range(5)]
    )
    assert all(results) is True  # nobody was spuriously logged out
    assert calls["redeems"] == 1  # exactly one redemption hit Entra
    assert _reval["deleted"] == []  # no session deleted by a losing racer


# --- logout: POST-only, returns the navigation target ------------------------


@pytest.fixture
def auth_client():
    app = FastAPI()
    app.include_router(auth_oidc.router, prefix="/api")
    return TestClient(app)


def test_logout_get_is_gone(auth_client):
    assert auth_client.get("/api/auth/logout").status_code == 405


def test_logout_post_local_only(auth_client):
    res = auth_client.post("/api/auth/logout")
    assert res.status_code == 200
    assert res.json() == {"logout_url": "/"}


def test_logout_post_entra_front_channel(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "logout_from_entra", True)
    monkeypatch.setattr(settings, "entra_tenant_id", "tenant-123")
    monkeypatch.setattr(settings, "app_base_url", "https://ragline.corp.example")
    url = auth_client.post("/api/auth/logout").json()["logout_url"]
    assert url.startswith("https://login.microsoftonline.com/tenant-123/oauth2/v2.0/logout")
    assert "post_logout_redirect_uri=https%3A%2F%2Fragline.corp.example" in url


# --- admin: immediate session revocation -------------------------------------


def test_admin_revoke_sessions(monkeypatch):
    app = FastAPI()
    app.include_router(admin_route.router, prefix="/api")
    app.dependency_overrides[require_admin] = lambda: AuthedUser(oid="admin-1")

    async def fake_delete_for_user(oid):
        fake_delete_for_user.called_with = oid
        return 3

    monkeypatch.setattr(auth_models, "delete_sessions_for_user", fake_delete_for_user)
    res = TestClient(app).post(f"/api/admin/users/{OID}/revoke-sessions")
    assert res.status_code == 200
    assert res.json() == {"revoked": 3, "oid": OID}
    assert fake_delete_for_user.called_with == OID


# --- health: anonymous callers get status only -------------------------------


@pytest.fixture
def health_client(monkeypatch):
    monkeypatch.setattr(health_module, "_cache", {"expires": 0.0, "data": None})

    async def fake_probes():
        return {"llm": True, "embedder": True, "reranker": None}

    monkeypatch.setattr(health_module, "probe_services", fake_probes)

    class _VS:
        async def ping(self):
            return True

    app = FastAPI()
    app.include_router(health_module.router, prefix="/api")
    app.dependency_overrides[get_vector_store] = lambda: _VS()
    return TestClient(app)


def test_health_anonymous_is_bare_status(health_client):
    settings.auth_enabled = True  # no middleware in this app -> no user attached
    assert health_client.get("/api/health").json() == {"status": "ok"}


def test_health_auth_off_full_body(health_client):
    settings.auth_enabled = False
    body = health_client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["qdrant"] is True and body["llm"] is True  # detail present


# --- file-based secrets (LoadCredential=) ------------------------------------


def test_file_secret_overrides_inline(tmp_path):
    from ragline.config import Settings

    secret_file = tmp_path / "session_secret"
    secret_file.write_text("from-file\n")
    s = Settings(session_secret="inline", session_secret_file=str(secret_file))
    assert s.session_secret == "from-file"


def test_missing_secret_file_fails_loudly(tmp_path):
    from ragline.config import Settings

    with pytest.raises(Exception):
        Settings(session_secret_file=str(tmp_path / "does-not-exist"))


# --- escape-hatch guard: parsed-bool, every falsey spelling ------------------


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "False", "OFF", "No"])
def test_falsey_auth_forms_all_parse_false(value):
    from ragline.config import Settings

    # The whole point of the app-level guard: it keys off THIS parsed bool, so
    # every spelling the systemd grep might miss still reads as disabled.
    assert Settings(auth_enabled=value).auth_enabled is False


def test_startup_guard_blocks_auth_off_without_marker(monkeypatch):
    from ragline import main

    monkeypatch.setattr(main.settings, "auth_enabled", False)
    monkeypatch.delenv("RAGLINE_ALLOW_INSECURE_DEV", raising=False)
    # The marker counts from either source; pin BOTH off (the .env on a dev
    # box legitimately sets the settings field).
    monkeypatch.setattr(main.settings, "ragline_allow_insecure_dev", False)
    with pytest.raises(RuntimeError, match="RAGLINE_ALLOW_INSECURE_DEV"):
        main._enforce_auth_posture()


def test_startup_guard_allows_auth_off_with_marker(monkeypatch):
    from ragline import main

    monkeypatch.setattr(main.settings, "auth_enabled", False)
    monkeypatch.setenv("RAGLINE_ALLOW_INSECURE_DEV", "1")
    main._enforce_auth_posture()  # no raise


def test_startup_guard_allows_auth_off_with_dotenv_marker(monkeypatch):
    # The marker also counts when it arrives via .env (settings field) rather
    # than an exported env var — how a dev box typically sets it.
    from ragline import main

    monkeypatch.setattr(main.settings, "auth_enabled", False)
    monkeypatch.delenv("RAGLINE_ALLOW_INSECURE_DEV", raising=False)
    monkeypatch.setattr(main.settings, "ragline_allow_insecure_dev", True)
    main._enforce_auth_posture()  # no raise


def test_startup_guard_noop_when_auth_on(monkeypatch):
    from ragline import main

    monkeypatch.setattr(main.settings, "auth_enabled", True)
    monkeypatch.delenv("RAGLINE_ALLOW_INSECURE_DEV", raising=False)
    main._enforce_auth_posture()  # auth on -> marker irrelevant, no raise
