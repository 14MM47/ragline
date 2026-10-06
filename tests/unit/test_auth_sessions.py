"""Session cookie signing + the per-user memory-store scoping.

The cookie tests pin the fail-closed edge: any value that wasn't produced by
sign_session_id with the current SESSION_SECRET unsigns to None. The scoping
tests prove the property the session routes rely on: two users' stores are
physically disjoint directories, so cross-user listing/loading/deleting is
impossible by construction rather than by filtering.
"""

from ragline.api.dependencies import get_memory_store
from ragline.auth.dependencies import DEV_USER, AuthedUser
from ragline.auth.sessions import sign_session_id, unsign_session_id
from ragline.chat.models import SessionMemory
from ragline.config import settings


def test_sign_unsign_round_trip():
    assert unsign_session_id(sign_session_id("abc-123")) == "abc-123"


def test_unsigned_value_rejected():
    assert unsign_session_id("abc-123") is None


def test_tampered_signature_rejected():
    signed = sign_session_id("abc-123")
    assert unsign_session_id(signed[:-2] + "xx") is None


def test_secret_rotation_invalidates_cookies():
    signed = sign_session_id("abc-123")
    old = settings.session_secret
    settings.session_secret = "rotated"
    try:
        assert unsign_session_id(signed) is None
    finally:
        settings.session_secret = old


def _user(oid: str) -> AuthedUser:
    return AuthedUser(oid=oid, upn=f"{oid}@corp.example")


def test_memory_stores_disjoint_per_user(tmp_path):
    settings.auth_enabled = True
    old_dir = settings.memory_dir
    settings.memory_dir = str(tmp_path)
    try:
        store_a = get_memory_store(_user("aaaa-1111"))
        store_b = get_memory_store(_user("bbbb-2222"))

        store_a.save(SessionMemory(session_id="s1", created_at="2026-08-10T00:00:00Z"))

        # A sees its session; B sees nothing, and B's delete of A's id is a no-op.
        assert [s["session_id"] for s in store_a.list_sessions()] == ["s1"]
        assert store_b.list_sessions() == []
        assert store_b.delete("s1") is False
        assert store_a.delete("s1") is True
    finally:
        settings.memory_dir = old_dir


def test_auth_off_uses_unscoped_store(tmp_path):
    # Dev mode must keep the historical behaviour: one shared store at the root.
    settings.auth_enabled = False
    store = get_memory_store(DEV_USER)
    # The lru-cached base store points at the configured memory_dir root.
    assert store is get_memory_store(_user("anyone-else"))
