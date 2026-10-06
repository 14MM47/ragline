"""Original-path joining tests — the citation-provenance feature's core rule:
separator style follows the BASE path (UNC/Windows vs POSIX)."""

from ragline.storage.paths import folder_path, join_original_path, upload_root


def test_unc_base_converts_separators():
    """A UNC base makes the whole path Windows-style."""
    assert (
        join_original_path("\\\\server\\share\\ProjectA", "vfd/abb/acs880.pdf")
        == "\\\\server\\share\\ProjectA\\vfd\\abb\\acs880.pdf"
    )


def test_windows_drive_base():
    """A drive-letter base with backslashes is treated as Windows-style."""
    assert (
        join_original_path("P:\\Projects\\SiteB", "sensors/ifm/og5.pdf")
        == "P:\\Projects\\SiteB\\sensors\\ifm\\og5.pdf"
    )


def test_posix_base_keeps_forward_slashes():
    """A POSIX base joins with forward slashes."""
    assert (
        join_original_path("/mnt/projects/siteb", "plc/siemens/s7.pdf")
        == "/mnt/projects/siteb/plc/siemens/s7.pdf"
    )


def test_trailing_separator_on_base_is_normalized():
    """A trailing separator on the base never doubles up."""
    assert (
        join_original_path("\\\\server\\share\\", "doc.pdf")
        == "\\\\server\\share\\doc.pdf"
    )
    assert join_original_path("/mnt/share/", "doc.pdf") == "/mnt/share/doc.pdf"


def test_empty_base_returns_relative_path():
    """No base -> the relative path alone is the provenance."""
    assert join_original_path("", "vfd/abb/acs880.pdf") == "vfd/abb/acs880.pdf"


def test_empty_relative_returns_base():
    """No relative path (single-file case) -> the base alone."""
    assert join_original_path("\\\\server\\share\\file.pdf", "") == "\\\\server\\share\\file.pdf"


def test_whitespace_is_stripped():
    """Copy-pasted paths often carry stray whitespace — stripped, not stored."""
    assert (
        join_original_path("  \\\\server\\share ", "doc.pdf")
        == "\\\\server\\share\\doc.pdf"
    )


# --- Explorer-tree derivation (Documents tab folder view) -------------------




def test_upload_root_inverts_unc_join():
    """Root = what join_original_path was given as the base, UNC style."""
    original = join_original_path("\\\\server\\share\\ProjectA", "vfd/abb/acs880.pdf")
    assert upload_root(original, "vfd/abb/acs880.pdf") == "\\\\server\\share\\ProjectA"


def test_upload_root_inverts_posix_join():
    """Same rule with a POSIX base and forward slashes."""
    original = join_original_path("/mnt/projects/siteb", "plc/siemens/s7.pdf")
    assert upload_root(original, "plc/siemens/s7.pdf") == "/mnt/projects/siteb"


def test_upload_root_single_file_upload_is_its_folder():
    """A single upload stores the full file path; source_path is the basename."""
    assert upload_root("\\\\server\\share\\file.pdf", "file.pdf") == "\\\\server\\share"


def test_upload_root_blank_when_nothing_to_derive():
    """No original path (or ACL-blanked) and mismatched suffixes give ""."""
    assert upload_root("", "a/b.pdf") == ""
    assert upload_root("\\\\server\\share\\other.pdf", "a/b.pdf") == ""
    # The relative path alone (empty base at ingest) has no root either.
    assert upload_root("a/b.pdf", "a/b.pdf") == ""


def test_folder_path_is_directory_part():
    """Directory part of the upload-relative path, always "/"-separated."""
    assert folder_path("plc/siemens/s7.pdf") == "plc/siemens"
    assert folder_path("manual.pdf") == ""
    assert folder_path("legacy\\rows\\x.pdf") == "legacy/rows"
    assert folder_path("") == ""
