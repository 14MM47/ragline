r"""Original-path joining — builds each document's original network location.

NEW in ragline (no raggles equivalent). Batch uploads may supply an
"original base path" (where the files really live, e.g. a UNC share). Each
file's original_path = base + its relative path inside the upload — but the
base may be a Windows UNC path (\\server\share\ProjectA) or a POSIX path
(/mnt/projects/a), while ZIP-relative paths always use forward slashes.
This module owns that join logic so it is unit-testable in isolation.
"""


def join_original_path(base: str, rel_path: str) -> str:
    """Join a user-supplied base path with an upload-relative path.

    Separator style is detected from the BASE: a base that starts with a UNC
    prefix (\\\\) or contains any backslash is treated as Windows-style, and
    the relative path's forward slashes become backslashes. Otherwise both
    sides join with "/". The base is otherwise stored verbatim — no case
    folding, no normalization — because it is provenance, not a path we open.
    """
    # Normalize inputs: strip whitespace, drop a trailing separator on the base.
    base = base.strip().rstrip("/\\")
    rel = rel_path.strip().lstrip("/\\")

    # No base -> the relative path alone is all the provenance we have.
    if not base:
        return rel
    # No relative path -> the base alone (single-file upload case).
    if not rel:
        return base

    # Windows-style detection from the base's own separators.
    is_windows = base.startswith("\\\\") or "\\" in base
    if is_windows:
        # ZIP entries always use "/" — convert for a consistent UNC display.
        return base + "\\" + rel.replace("/", "\\")
    return base + "/" + rel


# --- Folder-tree derivation (Documents tab explorer) ------------------------
#
# The Documents tab groups files by where they were uploaded FROM. Nothing new
# is stored for that: the two columns already on every Document row are enough.
#   upload root  = original_path minus the upload-relative source_path suffix
#                  (i.e. the original_base_path the uploader typed), and
#   folder path  = the directory part of source_path (forward slashes).
# Both helpers are pure string functions so the rule is unit-testable and the
# listing endpoint stays a thin loop.


def upload_root(original_path: str, source_path: str) -> str:
    """Recover the upload root that `original_path` was joined from.

    Inverse of join_original_path(): if original_path ends with source_path
    (in either separator style, preceded by a separator) the root is what
    comes before it. A single-file upload stores the FULL file path as
    original_path with just the basename as source_path, so the same rule
    yields its containing folder. Returns "" when original_path is empty or
    does not end with the relative path (nothing to derive from).
    """
    original = original_path.strip()
    rel = source_path.strip().strip("/\\")
    if not original or not rel:
        return ""
    # Try both separator styles — the stored path follows the BASE's style
    # (see join_original_path) while source_path is always "/"-separated.
    for candidate in (rel.replace("/", "\\"), rel.replace("\\", "/")):
        for sep in ("\\", "/"):
            suffix = sep + candidate
            if original.endswith(suffix) and len(original) > len(suffix):
                return original[: -len(suffix)]
    return ""


def folder_path(source_path: str) -> str:
    """Directory part of an upload-relative path, "/"-separated ("" = top level).

    `plc/siemens/s7.pdf` -> `plc/siemens`; `manual.pdf` -> "". Backslashes
    are tolerated (legacy rows) but the result always uses "/" so the front
    end splits on one separator.
    """
    rel = source_path.strip().replace("\\", "/").strip("/")
    if "/" not in rel:
        return ""
    return rel.rsplit("/", 1)[0]
