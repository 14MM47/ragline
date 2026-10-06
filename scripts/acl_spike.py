"""Day-1 ACL spike — validate the whole ACL-gating design before trusting it.

    uv run python scripts/acl_spike.py '\\\\fs1\\share\\path\\file.pdf' [more paths...]

For each path, with the SMB service account from .env:
  1. canonicalize the UNC (does the free-text original_path shape parse?)
  2. fetch the security descriptor (does READ_CONTROL work from Linux?)
  3. dump owner/group/every DACL ACE with its raw SID
  4. resolve each SID (are they the expected S-1-12-1-* cloud SIDs and
     well-known SIDs, or something the cloud-only assumption didn't predict?)

Read-only throughout; nothing is written to the database. Run it against
~20 real files with deliberately mixed permissions and eyeball the output
BEFORE enabling the crawler timer.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ragline.acl.paths import canonicalize_unc  # noqa: E402
from ragline.acl.sid_map import sid_to_principal  # noqa: E402
from ragline.acl.smb import evaluate_dacl, fetch_security_descriptor  # noqa: E402
from ragline.config import settings  # noqa: E402


def inspect_path(raw_path: str) -> None:
    print(f"\n=== {raw_path}")
    canonical = canonicalize_unc(raw_path)
    print(f"  canonical: {canonical}")
    if canonical is None:
        print("  -> would fail closed (blank_path)")
        return

    try:
        sd = fetch_security_descriptor(canonical, settings.smb_username, settings.smb_password)
    except Exception as e:
        print(f"  FETCH FAILED: {type(e).__name__}: {e}")
        return

    print(f"  owner: {sd.get_owner()}")
    print(f"  group: {sd.get_group()}")
    dacl = sd.get_dacl()
    if dacl is None:
        print("  DACL: none (Windows: everyone has access)")
    else:
        for ace in dacl["aces"].get_value():
            try:
                sid = str(ace["sid"])
                resolved = sid_to_principal(sid)
                print(
                    f"  ACE type={ace['ace_type'].get_value()} "
                    f"flags=0x{ace['ace_flags'].get_value():02x} "
                    f"mask=0x{ace['mask'].get_value():08x} "
                    f"sid={sid} -> {resolved if resolved else 'IGNORED (fail closed)'}"
                )
            except Exception as e:
                print(f"  ACE unparseable: {e}")

    result = evaluate_dacl(sd)
    print(f"  => allow_all_authenticated={result.allow_all_authenticated}")
    print(f"  => principals={result.principals}")
    if result.denied:
        print(f"  => denied (beats any allow): {result.denied}")
    if result.unresolved_sids:
        print(f"  => unresolved (ignored): {result.unresolved_sids}")


def main() -> int:
    # -h/--help prints the usage text and succeeds; no arguments prints it and fails.
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print(__doc__)
        return 0
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    if not settings.smb_username or not settings.smb_password:
        print("SMB_USERNAME / SMB_PASSWORD not set in .env", file=sys.stderr)
        return 1
    for path in sys.argv[1:]:
        inspect_path(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
