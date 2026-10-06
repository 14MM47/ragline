"""SID <-> Entra object-id mapping — golden vectors and fail-closed edges.

The hand-derived vectors pin the byte order independently of the code under
test: bytes_le (== .NET Guid.ToByteArray()) split into four little-endian
DWORDs. If either endianness assumption regresses, these break.
"""

import uuid

from ragline.acl.sid_map import ALL_AUTHENTICATED, oid_to_sid, sid_to_principal


# Hand-derived: GUID ...-000000000001 -> last DWORD bytes are 00 00 00 01,
# little-endian value 0x01000000 = 16777216.
def test_golden_vector_trailing_byte():
    assert oid_to_sid("00000000-0000-0000-0000-000000000001") == "S-1-12-1-0-0-0-16777216"


# Hand-derived: time_low=0x01000000 serializes little-endian as 00 00 00 01,
# read back as DWORD 0x01000000 = 16777216 in the FIRST position.
def test_golden_vector_leading_field():
    assert oid_to_sid("01000000-0000-0000-0000-000000000000") == "S-1-12-1-16777216-0-0-0"


def test_round_trip_arbitrary_oids():
    for oid in [
        "aaaabbbb-cccc-dddd-eeee-ffff00001111",
        str(uuid.UUID(int=2**128 - 1)),
        "12345678-1234-5678-1234-567812345678",
    ]:
        assert sid_to_principal(oid_to_sid(oid)) == oid


def test_case_insensitive():
    sid = oid_to_sid("12345678-1234-5678-1234-567812345678")
    assert sid_to_principal(sid.lower()) == "12345678-1234-5678-1234-567812345678"


def test_well_known_all_authenticated():
    assert sid_to_principal("S-1-1-0") == ALL_AUTHENTICATED       # Everyone
    assert sid_to_principal("S-1-5-11") == ALL_AUTHENTICATED      # Authenticated Users
    assert sid_to_principal("S-1-5-32-545") == ALL_AUTHENTICATED  # BUILTIN\Users


def test_unresolvable_sids_ignored():
    # Legacy domain SID, service SID, malformed cloud SIDs: all None.
    assert sid_to_principal("S-1-5-21-1004336348-1177238915-682003330-512") is None
    assert sid_to_principal("S-1-5-18") is None
    assert sid_to_principal("S-1-12-1-1-2-3") is None          # too few dwords
    assert sid_to_principal("S-1-12-1-1-2-3-4-5") is None      # too many
    assert sid_to_principal("S-1-12-1-x-2-3-4") is None        # not a number
    assert sid_to_principal("") is None
