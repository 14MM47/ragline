"""SID <-> Entra object id mapping for a CLOUD-ONLY tenant.

NTFS DACLs written from Entra-joined Windows machines represent cloud
principals with SIDs of the form S-1-12-1-a-b-c-d, where the four
sub-authorities are the principal's Entra object GUID as four little-endian
DWORDs in .NET Guid.ToByteArray() order (== Python uuid.bytes_le). The
mapping is pure arithmetic — no directory lookup, no sync table.

Well-known SIDs that mean "any signed-in user" map to the ALL_AUTHENTICATED
sentinel. Every other SID (legacy machine-local accounts, NT AUTHORITY
service identities, capability SIDs, ...) resolves to None and is IGNORED —
an unrecognized principal never grants access (fail closed).

Validate against real DACLs with scripts/acl_spike.py before the crawler is
trusted.
"""

import struct
import uuid

# Sentinel returned for SIDs that mean "every authenticated user".
ALL_AUTHENTICATED = "*"

# S-1-1-0        Everyone
# S-1-5-11       NT AUTHORITY\Authenticated Users
# S-1-5-32-545   BUILTIN\Users (every interactive account on the file server)
_WELL_KNOWN_ALL = {"s-1-1-0", "s-1-5-11", "s-1-5-32-545"}

_CLOUD_PREFIX = "s-1-12-1-"


def sid_to_principal(sid: str) -> str | None:
    """SID string -> Entra object id, ALL_AUTHENTICATED, or None (ignore)."""
    s = sid.strip().lower()
    if s in _WELL_KNOWN_ALL:
        return ALL_AUTHENTICATED
    if not s.startswith(_CLOUD_PREFIX):
        return None
    tail = s[len(_CLOUD_PREFIX):].split("-")
    if len(tail) != 4:
        return None
    try:
        dwords = [int(p) for p in tail]
        if any(d < 0 or d > 0xFFFFFFFF for d in dwords):
            return None
        raw = struct.pack("<IIII", *dwords)
    except (ValueError, struct.error):
        return None
    return str(uuid.UUID(bytes_le=raw))


def oid_to_sid(oid: str) -> str:
    """Entra object id -> its cloud SID (used by tests and the spike script)."""
    dwords = struct.unpack("<IIII", uuid.UUID(oid).bytes_le)
    return "S-1-12-1-" + "-".join(str(d) for d in dwords)
