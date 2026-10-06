"""SMB security-descriptor fetch + DACL evaluation.

Split on purpose: fetch_security_descriptor() is the only function that
touches the network (smbprotocol, exercised by scripts/acl_spike.py and the
crawler); evaluate_dacl() is pure and unit-tested against synthetic
descriptors built with the same smbprotocol structures.

DACL semantics implemented (conservative subset of Windows access checks):
  * An ACE grants/denies READ when its mask includes FILE_READ_DATA,
    GENERIC_READ, or GENERIC_ALL.
  * ACCESS_DENIED ACEs win: denied principals are returned SEPARATELY so the
    access check can subtract them against the requesting user's whole
    identity (oid + groups), not just against identical allow entries —
    a user denied by name loses access even when allowed via a group
    (Windows evaluates deny-first in canonical order; deny-always-wins is
    the safe approximation).
  * INHERIT_ONLY ACEs don't apply to the object itself and are skipped.
  * SIDs resolve via acl/sid_map.py; unresolvable SIDs are ignored, so an
    unknown principal can only ever LOSE access (a deny from an unknown
    "everyone-like" SID cannot be modelled — acceptable: that errs closed
    for allows and open only for exotic deny rules, which the spike checks).
  * No DACL present at all means Windows grants everyone access -> mapped to
    allow_all_authenticated.
"""

from dataclasses import dataclass, field

from smbprotocol.security_descriptor import AceType, SMB2CreateSDBuffer

from ragline.acl.sid_map import ALL_AUTHENTICATED, sid_to_principal

# Read-granting bits: FILE_READ_DATA | GENERIC_ALL | GENERIC_READ.
_READ_MASK = 0x00000001 | 0x10000000 | 0x80000000

# ACE inheritance flag: applies only to children, not this object.
_INHERIT_ONLY = 0x08

# SecurityInformation bits for the QUERY_INFO request.
OWNER_SECURITY_INFORMATION = 0x00000001
GROUP_SECURITY_INFORMATION = 0x00000002
DACL_SECURITY_INFORMATION = 0x00000004


@dataclass
class DaclResult:
    """Resolved read-access for one file."""

    allow_all_authenticated: bool = False
    principals: list[str] = field(default_factory=list)  # Entra object ids
    # Read-DENIED Entra object ids. Kept separate (not just subtracted from
    # principals) because a deny must also beat an allow granted through a
    # DIFFERENT principal — e.g. user denied by name, allowed via group.
    denied: list[str] = field(default_factory=list)
    # Raw SID strings the resolver ignored — surfaced by the spike script so
    # unexpected populations are seen, not silently dropped.
    unresolved_sids: list[str] = field(default_factory=list)


def fetch_security_descriptor(unc_path: str, username: str, password: str) -> SMB2CreateSDBuffer:
    """Read a file's security descriptor (owner/group/DACL) over SMB.

    Opens with READ_CONTROL only — the service account does not need (and
    should not have) permission to read the file's data.
    """
    from smbclient._io import SMBFileTransaction, SMBRawIO
    from smbprotocol.open import (
        FilePipePrinterAccessMask,
        SMB2QueryInfoRequest,
        SMB2QueryInfoResponse,
    )
    from smbprotocol.query_info import InfoType

    raw = SMBRawIO(
        unc_path,
        mode="r",
        share_access="rwd",  # never block the business from using the file
        desired_access=FilePipePrinterAccessMask.READ_CONTROL,
        username=username,
        password=password,
    )
    with SMBFileTransaction(raw) as transaction:
        req = SMB2QueryInfoRequest()
        req["info_type"] = InfoType.SMB2_0_INFO_SECURITY
        req["output_buffer_length"] = 65535
        req["additional_information"] = (
            OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
        )
        req["file_id"] = transaction.raw.fd.file_id

        def _receive(request):
            response = transaction.raw.fd.connection.receive(request)
            query_resp = SMB2QueryInfoResponse()
            query_resp.unpack(response["data"].get_value())
            sd = SMB2CreateSDBuffer()
            sd.unpack(query_resp["buffer"].get_value())
            return sd

        transaction += (req, _receive)

    return transaction.results[0]


def evaluate_dacl(sd: SMB2CreateSDBuffer) -> DaclResult:
    """Security descriptor -> resolved read-access (pure, unit-tested)."""
    result = DaclResult()
    dacl = sd.get_dacl()
    if dacl is None:
        # NULL DACL: Windows semantics are "everyone has full access".
        result.allow_all_authenticated = True
        return result

    allowed: set[str] = set()
    denied: set[str] = set()
    allow_all = False
    deny_all = False

    for ace in dacl["aces"].get_value():
        try:
            ace_type = ace["ace_type"].get_value()
            if ace_type not in (AceType.ACCESS_ALLOWED_ACE_TYPE, AceType.ACCESS_DENIED_ACE_TYPE):
                continue
            if ace["ace_flags"].get_value() & _INHERIT_ONLY:
                continue
            if not (ace["mask"].get_value() & _READ_MASK):
                continue
            principal = sid_to_principal(str(ace["sid"]))
            if principal is None:
                result.unresolved_sids.append(str(ace["sid"]))
                continue
            if ace_type == AceType.ACCESS_ALLOWED_ACE_TYPE:
                if principal == ALL_AUTHENTICATED:
                    allow_all = True
                else:
                    allowed.add(principal)
            else:
                if principal == ALL_AUTHENTICATED:
                    deny_all = True
                else:
                    denied.add(principal)
        except Exception:
            # A malformed ACE never grants; skip it and keep evaluating.
            continue

    result.denied = sorted(denied)
    if deny_all:
        # Read denied to an everyone-class principal: nobody gets a link.
        return result

    result.allow_all_authenticated = allow_all
    result.principals = sorted(allowed - denied)
    return result
