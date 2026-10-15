"""scripts/export_public.py — masking of private identifiers before a public export."""

import importlib.util
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_spec = importlib.util.spec_from_file_location("export_public_script", SCRIPTS / "export_public.py")
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)


# Made-up ids, assembled at run time so this file's own text never looks like
# one (the export masks ids it finds anywhere in the tree).
POD = "zz11fake" + "00pod1"
VOL = "zz11" + "fakev1"
WORD = "ordinaryword7a"


def test_pod_and_volume_ids_masked_only_in_context():
    """Ids on pod/volume lines are masked; a 14-character word elsewhere is left alone."""
    text = (f'pod = "{POD}"\nnetwork volume {VOL} in EU-RO-1\n'
            f"https://{POD}-8000.proxy.runpod.net\n{WORD} is a product\n")
    out, n = ex.mask_text(text)
    assert POD not in out and VOL not in out
    assert "<pod-id>-8000.proxy" in out and "<volume-id>" in out and f"{WORD} is a product" in out
    assert n == 3


def test_local_paths_masked():
    """Home and Windows profile paths lose the user name; the repo path becomes relative."""
    text = (f'"results_file": "{ex.REPO}/eval/results/x.json"\n~/.config/podlink\n'
            "/mnt/c/Users/<user>/Documents/archive\n%USERPROFILE%\\Documents\n")
    out, _ = ex.mask_text(text)
    assert '"results_file": "eval/results/x.json"' in out and "~/.config/podlink" in out
    assert "/mnt/c/Users/<user>/Documents" in out and "%USERPROFILE%\\Documents" in out
    assert "Someone" not in out and "someone" not in out


def test_known_ids_collects_ids_named_in_context():
    """An id named on a pod line is collected, so its bare mentions elsewhere can be masked too."""
    assert ex.known_ids(f"Pod `{POD}` was ready\nplain {POD}\n") == {POD}
