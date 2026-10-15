"""export_public.py — export the committed tree for the public repository (docs/publishing.md).

    python scripts/export_public.py OUT_DIR [--rev HEAD] [--campaign eval/results/eval-2026-10]

Archives one commit (never the working tree, never the Git history) into a new
empty directory, then:

1. masks private identifiers in every text file: RunPod pod and network-volume
   ids, this machine's home and Windows profile paths;
2. rebuilds the evaluation page with `eval_dashboard.py --public` (ladder rungs
   only, no spend ledger or pod ids) over the committed campaign results;
3. scans the result for anything that still looks private and exits non-zero
   if it finds any, so the export cannot be committed by accident.

Gitleaks and the environment-value comparison in docs/publishing.md still run
on the exported tree afterwards; this script does not replace them.
"""

import argparse
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# A RunPod pod id (14) or network-volume id (10): lowercase letters and digits,
# at least one of each. Only masked where the line talks about a pod, volume or
# proxy, so ordinary 14-letter words and hex addresses are left alone.
_POD = re.compile(r"\b(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{14}\b")
_VOLUME = re.compile(r"\b(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{10}\b")
_POD_CONTEXT = re.compile(r"pod|proxy|session", re.IGNORECASE)
_VOLUME_CONTEXT = re.compile(r"volume", re.IGNORECASE)
# Local paths: the repo checkout first (made repo-relative), then the home and
# Windows profile directories.
_PATHS = [
    (re.compile(re.escape(str(REPO)) + r"/?"), ""),
    (re.compile(r"/home/[a-z_][a-z0-9_-]*"), "~"),
    (re.compile(r"/mnt/c/Users/<user>/\s\"'`]+"), "/mnt/c/Users/<user>"),
    (re.compile(r"C:\\+Users\\+[^\\\s\"'`]+", re.IGNORECASE), r"%USERPROFILE%"),
]
# What must not survive the export (checked after masking).
_RESIDUAL = [re.compile(r"/home/[a-z]"), re.compile(r"C:\\+Users\\+(?!<)", re.IGNORECASE),
             re.compile(r"/mnt/c/Users/<user>")]


def mask_text(text: str) -> tuple[str, int]:
    """Mask private identifiers in one file's text; returns (text, replacements)."""
    count = 0
    lines = []
    for line in text.splitlines(keepends=True):
        # Ids are only masked on lines that are about pods/volumes.
        if _POD_CONTEXT.search(line):
            line, n = _POD.subn("<pod-id>", line)
            count += n
        if _VOLUME_CONTEXT.search(line):
            line, n = _VOLUME.subn("<volume-id>", line)
            count += n
        lines.append(line)
    text = "".join(lines)
    for pattern, repl in _PATHS:
        text, n = pattern.subn(lambda _m, r=repl: r, text)
        count += n
    return text, count


def known_ids(text: str) -> set[str]:
    """Pod/volume ids named anywhere in the tree (to catch them on lines without context words)."""
    ids = set()
    for line in text.splitlines():
        if _POD_CONTEXT.search(line):
            ids |= set(_POD.findall(line))
        if _VOLUME_CONTEXT.search(line):
            ids |= set(_VOLUME.findall(line))
    return ids


def main(argv: list[str] | None = None) -> int:
    """Archive, mask, rebuild the page, scan."""
    parser = argparse.ArgumentParser(description="Export the committed tree for the public repository")
    parser.add_argument("out_dir", help="New or empty directory to export into")
    parser.add_argument("--rev", default="HEAD", help="Commit to export (default HEAD)")
    parser.add_argument("--campaign", default="eval/results/eval-2026-10", help="Campaign results directory")
    args = parser.parse_args(argv)
    out = Path(args.out_dir)
    if out.exists() and any(out.iterdir()):
        print(f"{out} is not empty", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)

    # 1. The committed tree only: git archive of one revision.
    with tempfile.TemporaryFile() as tar:
        subprocess.run(["git", "-C", str(REPO), "archive", args.rev], stdout=tar, check=True)
        tar.seek(0)
        with tarfile.open(fileobj=tar) as tf:
            tf.extractall(out, filter="data")

    # 2. The public page, rebuilt from the exported (committed) results.
    campaign = out / args.campaign
    if campaign.is_dir():
        subprocess.run([sys.executable, str(REPO / "scripts" / "eval_dashboard.py"), str(campaign), "--public",
                        "--golden", str(out / "eval" / "golden_set_hmi.json"),
                        "--campaign-file", str(out / "eval" / "campaign" / f"{campaign.name}.toml"),
                        "-o", str(campaign / "dashboard.html")], check=True, cwd=out)

    # 3. Mask, in two passes: collect ids named anywhere, then replace them everywhere.
    texts = {}
    for path in sorted(p for p in out.rglob("*") if p.is_file()):
        try:
            texts[path] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            continue  # binary files are not scanned
    ids = set().union(*(known_ids(t) for t in texts.values())) if texts else set()
    total = 0
    for path, text in texts.items():
        masked, n = mask_text(text)
        for i in ids:
            masked, k = re.subn(rf"\b{re.escape(i)}\b", "<pod-id>" if len(i) == 14 else "<volume-id>", masked)
            n += k
        if n:
            path.write_text(masked, encoding="utf-8")
            total += n
    print(f"exported {args.rev} to {out}: {len(texts)} text files, {total} replacements, {len(ids)} ids masked")

    # 4. Residual scan: anything still private fails the export.
    bad = [(p, pat.pattern) for p in texts for pat in _RESIDUAL if pat.search(p.read_text(encoding="utf-8"))]
    bad += [(p, i) for p in texts for i in ids if i in p.read_text(encoding="utf-8")]
    for path, what in bad:
        print(f"RESIDUAL {path.relative_to(out)}: {what}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
