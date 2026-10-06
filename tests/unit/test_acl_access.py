"""DACL evaluation + the access truth table — every fail-closed branch.

The descriptors are built with the same smbprotocol structures the fetch
path unpacks, so evaluate_dacl() is tested against the real wire format,
not a hand-rolled approximation.
"""

from datetime import datetime, timedelta, timezone

import pytest
from smbprotocol.security_descriptor import (
    AccessAllowedAce,
    AccessDeniedAce,
    AclPacket,
    SIDPacket,
    SMB2CreateSDBuffer,
)

from ragline.acl.access import accessible
from ragline.acl.sid_map import oid_to_sid
from ragline.acl.smb import evaluate_dacl
from ragline.auth.dependencies import AuthedUser
from ragline.storage.acl_models import DocumentAcl

OID_ALICE = "11111111-1111-1111-1111-111111111111"
OID_GROUP = "22222222-2222-2222-2222-222222222222"
OID_OTHER = "33333333-3333-3333-3333-333333333333"

FILE_READ_DATA = 0x00000001
GENERIC_READ = 0x80000000
FILE_WRITE_DATA = 0x00000002


def _sid(value: str) -> SIDPacket:
    sid = SIDPacket()
    sid.from_string(value)
    return sid


def _allow(sid: str, mask: int) -> AccessAllowedAce:
    ace = AccessAllowedAce()
    ace["mask"] = mask
    ace["sid"] = _sid(sid)
    return ace


def _deny(sid: str, mask: int) -> AccessDeniedAce:
    ace = AccessDeniedAce()
    ace["mask"] = mask
    ace["sid"] = _sid(sid)
    return ace


def _sd(aces: list | None) -> SMB2CreateSDBuffer:
    """Build a self-relative descriptor and round-trip it through pack/unpack."""
    sd = SMB2CreateSDBuffer()
    sd["control"].set_flag(0x8000)  # SE_SELF_RELATIVE
    if aces is not None:
        acl = AclPacket()
        # Assignment (not .append on the inner list) so the ListField
        # recomputes ace_count/acl_size for the packed form.
        acl["aces"] = aces
        sd.set_dacl(acl)
    packed = sd.pack()
    fresh = SMB2CreateSDBuffer()
    fresh.unpack(packed)
    return fresh


# --- evaluate_dacl ----------------------------------------------------------


def test_allow_ace_resolves_principal():
    result = evaluate_dacl(_sd([_allow(oid_to_sid(OID_ALICE), FILE_READ_DATA)]))
    assert result.principals == [OID_ALICE]
    assert not result.allow_all_authenticated


def test_generic_read_counts_as_read():
    result = evaluate_dacl(_sd([_allow(oid_to_sid(OID_ALICE), GENERIC_READ)]))
    assert result.principals == [OID_ALICE]


def test_write_only_ace_grants_nothing():
    result = evaluate_dacl(_sd([_allow(oid_to_sid(OID_ALICE), FILE_WRITE_DATA)]))
    assert result.principals == []


def test_everyone_allow_sets_all_authenticated():
    result = evaluate_dacl(_sd([_allow("S-1-1-0", FILE_READ_DATA)]))
    assert result.allow_all_authenticated


def test_deny_beats_allow():
    result = evaluate_dacl(
        _sd(
            [
                _allow(oid_to_sid(OID_ALICE), FILE_READ_DATA),
                _deny(oid_to_sid(OID_ALICE), FILE_READ_DATA),
                _allow(oid_to_sid(OID_GROUP), FILE_READ_DATA),
            ]
        )
    )
    assert result.principals == [OID_GROUP]
    assert result.denied == [OID_ALICE]


def test_deny_surfaced_even_without_matching_allow():
    # User denied by name, allowed only via a group: the deny must survive
    # into the result so the access check can subtract it against the user's
    # whole identity — the cross-principal case Windows resolves deny-first.
    result = evaluate_dacl(
        _sd(
            [
                _deny(oid_to_sid(OID_ALICE), FILE_READ_DATA),
                _allow(oid_to_sid(OID_GROUP), FILE_READ_DATA),
            ]
        )
    )
    assert result.principals == [OID_GROUP]
    assert result.denied == [OID_ALICE]


def test_everyone_deny_blocks_all():
    result = evaluate_dacl(
        _sd([_allow(oid_to_sid(OID_ALICE), FILE_READ_DATA), _deny("S-1-1-0", FILE_READ_DATA)])
    )
    assert result.principals == []
    assert not result.allow_all_authenticated


def test_write_only_deny_not_recorded():
    # A deny that doesn't cover read must not subtract read access.
    result = evaluate_dacl(
        _sd(
            [
                _allow(oid_to_sid(OID_ALICE), FILE_READ_DATA),
                _deny(oid_to_sid(OID_ALICE), FILE_WRITE_DATA),
            ]
        )
    )
    assert result.principals == [OID_ALICE]
    assert result.denied == []


def test_unresolvable_sid_ignored_but_surfaced():
    legacy = "S-1-5-21-1004336348-1177238915-682003330-513"
    result = evaluate_dacl(_sd([_allow(legacy, FILE_READ_DATA)]))
    assert result.principals == []
    assert legacy in result.unresolved_sids


def test_null_dacl_means_everyone():
    assert evaluate_dacl(_sd(None)).allow_all_authenticated


# --- accessible() truth table ------------------------------------------------


def _user(groups: list[str] | None = None) -> AuthedUser:
    return AuthedUser(oid=OID_ALICE, groups=groups or [])


def _acl(**kwargs) -> DocumentAcl:
    now = datetime.now(timezone.utc)
    defaults = dict(
        document_id="doc-1",
        crawl_status="ok",
        principals_json="[]",
        allow_all_authenticated=False,
        last_ok_at=now,
        crawled_at=now,
    )
    defaults.update(kwargs)
    return DocumentAcl(**defaults)


def test_no_acl_row_denies():
    assert accessible(_user(), None) is False


def test_stale_crawl_denies():
    stale = datetime.now(timezone.utc) - timedelta(days=30)
    acl = _acl(allow_all_authenticated=True, last_ok_at=stale)
    assert accessible(_user(), acl) is False


def test_never_succeeded_crawl_denies():
    acl = _acl(allow_all_authenticated=True, last_ok_at=None)
    assert accessible(_user(), acl) is False


@pytest.mark.parametrize("status", ["blank_path", "unreachable", "access_denied", "parse_error"])
def test_non_ok_status_denies(status):
    acl = _acl(crawl_status=status, allow_all_authenticated=True)
    assert accessible(_user(), acl) is False


def test_all_authenticated_allows():
    assert accessible(_user(), _acl(allow_all_authenticated=True)) is True


def test_own_oid_allows():
    acl = _acl(principals_json=f'["{OID_ALICE}"]')
    assert accessible(_user(), acl) is True


def test_group_intersection_allows():
    acl = _acl(principals_json=f'["{OID_GROUP}"]')
    assert accessible(_user(groups=[OID_GROUP]), acl) is True


def test_explicit_groups_override_snapshot():
    # Freshness-aware groups from Graph take precedence over the login snapshot.
    acl = _acl(principals_json=f'["{OID_GROUP}"]')
    user = _user(groups=[OID_GROUP])  # snapshot says member...
    assert accessible(user, acl, groups=[]) is False  # ...Graph refresh says not


def test_unrelated_user_denied():
    acl = _acl(principals_json=f'["{OID_OTHER}"]')
    assert accessible(_user(groups=[OID_GROUP]), acl) is False


# Deny-first: an explicit deny on ANY of the user's principals beats every
# allow, including one granted through a different principal (F1 fix).


def test_oid_deny_beats_group_allow():
    acl = _acl(principals_json=f'["{OID_GROUP}"]', denied_json=f'["{OID_ALICE}"]')
    assert accessible(_user(groups=[OID_GROUP]), acl) is False


def test_group_deny_beats_oid_allow():
    acl = _acl(principals_json=f'["{OID_ALICE}"]', denied_json=f'["{OID_GROUP}"]')
    assert accessible(_user(groups=[OID_GROUP]), acl) is False


def test_deny_beats_allow_all_authenticated():
    acl = _acl(allow_all_authenticated=True, denied_json=f'["{OID_ALICE}"]')
    assert accessible(_user(), acl) is False


def test_deny_on_unrelated_principal_is_harmless():
    acl = _acl(principals_json=f'["{OID_ALICE}"]', denied_json=f'["{OID_OTHER}"]')
    assert accessible(_user(), acl) is True
