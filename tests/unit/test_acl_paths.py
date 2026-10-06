"""original_path canonicalization — every variant folds to one key or None."""

from ragline.acl.paths import canonicalize_unc, split_unc
from ragline.config import settings


def test_classic_unc_lowercased():
    assert (
        canonicalize_unc(r"\\FS1\Share\ProjectA\Manual.PDF")
        == r"\\fs1\share\projecta\manual.pdf"
    )


def test_forward_slashes_folded():
    assert canonicalize_unc("//fs1/share/a/b.pdf") == r"\\fs1\share\a\b.pdf"


def test_long_path_prefix_stripped():
    assert canonicalize_unc(r"\\?\UNC\fs1\share\a.pdf") == r"\\fs1\share\a.pdf"


def test_trailing_and_doubled_separators():
    assert canonicalize_unc("\\\\fs1\\share\\a\\\\b.pdf\\") == r"\\fs1\share\a\b.pdf"


def test_host_alias_folding():
    old = settings.smb_host_aliases
    settings.smb_host_aliases = "fs1=fs1.corp.example;nas=nas01.corp.example"
    try:
        assert canonicalize_unc(r"\\FS1\eng\x.pdf") == r"\\fs1.corp.example\eng\x.pdf"
        assert canonicalize_unc(r"\\nas\dat\y.pdf") == r"\\nas01.corp.example\dat\y.pdf"
    finally:
        settings.smb_host_aliases = old


def test_non_unc_fails_closed():
    assert canonicalize_unc("") is None
    assert canonicalize_unc("   ") is None
    assert canonicalize_unc("C:\\local\\file.pdf") is None
    assert canonicalize_unc("just a note the uploader typed") is None
    assert canonicalize_unc(r"\\hostonly") is None  # no share component


def test_split_unc():
    assert split_unc(r"\\fs1\share\a\b.pdf") == ("fs1", "share", r"a\b.pdf")
