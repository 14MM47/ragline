"""Canonicalization of original_path values for ACL lookups.

Document.original_path is deliberately free text (storage/paths.py: it is
provenance, not a path we open) — but the crawler DOES open it, so the ACL
layer needs a trusted, comparable form. Canonical form:

    \\\\host\\share\\dir\\file.pdf   (lowercased, backslashes, no trailing sep)

Accepted inputs: classic UNC (\\\\host\\share\\...), forward-slash UNC
(//host/share/...), the long-path prefix (\\\\?\\UNC\\host\\share\\...), and
mixed separators. Host aliases (short name vs FQDN vs DFS namespace) are
folded via the SMB_HOST_ALIASES env map so "\\\\fs1\\eng" and
"\\\\fs1.corp.example\\eng" key identically.

Anything that cannot be read as \\\\host\\share\\<path> canonicalizes to None
and the document fails closed (crawl_status='blank_path').
"""

import re

from ragline.config import settings


def _alias_map() -> dict[str, str]:
    """SMB_HOST_ALIASES as {alias_lower: canonical_lower}. Empty = no folding."""
    mapping: dict[str, str] = {}
    for pair in settings.smb_host_aliases.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        alias, target = pair.split("=", 1)
        if alias.strip() and target.strip():
            mapping[alias.strip().lower()] = target.strip().lower()
    return mapping


def canonicalize_unc(raw: str) -> str | None:
    """Free-text original_path -> canonical UNC, or None (fail closed)."""
    if not raw or not raw.strip():
        return None
    path = raw.strip()

    # Long-path prefix: \\?\UNC\host\share\... -> \\host\share\...
    m = re.match(r"^\\\\\?\\UNC\\", path, flags=re.IGNORECASE)
    if m:
        path = "\\\\" + path[m.end():]

    # Unify separators, then require the UNC shape.
    path = path.replace("/", "\\")
    if not path.startswith("\\\\"):
        return None

    # Split into components, dropping empties from doubled separators.
    parts = [p for p in path.lstrip("\\").split("\\") if p]
    if len(parts) < 2:  # need at least host + share
        return None

    host = parts[0].lower()
    host = _alias_map().get(host, host)
    rest = [p.lower() for p in parts[1:]]
    return "\\\\" + "\\".join([host, *rest])


def split_unc(canonical: str) -> tuple[str, str, str]:
    """Canonical UNC -> (host, share, relative_path_with_backslashes)."""
    parts = canonical.lstrip("\\").split("\\")
    host, share = parts[0], parts[1]
    return host, share, "\\".join(parts[2:])
