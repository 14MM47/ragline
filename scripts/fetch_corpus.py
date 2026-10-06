"""fetch_corpus.py — rebuild the test corpus from its public index.

The datasheets ragline is evaluated on are not redistributed in this repo
(they are the vendors' copyright). eval/corpus/manifest.csv records, for each
one, the public URL it came from and the SHA-256 of the copy the evaluation
used. This script downloads them into the same directory tree the golden
question sets refer to, and checks each file against its recorded digest.

    python scripts/fetch_corpus.py --golden-only          # just the documents the golden set cites
    python scripts/fetch_corpus.py --category hmi         # the evaluated subset (~0.7 GB)
    python scripts/fetch_corpus.py                        # everything with a URL (~5 GB)
    python scripts/fetch_corpus.py --category hmi --dry-run

Then ingest:  python scripts/ingest.py testdata/hmi

What to expect:
  * Re-runs are cheap — a file already on disk with the right digest is skipped.
  * Some rows have no recorded URL. They are listed at the end with their
    title and digest; find them on the vendor's site and drop them in place.
  * Vendors revise and move documents. A file that downloads but no longer
    matches its digest is KEPT and reported as "changed": it is probably a
    newer revision, so page numbers in the golden set may have shifted. On
    later runs it shows as "differs" and is left alone (--force re-downloads).

Standard library only, one request at a time with a pause between them — this
is a courtesy download of public files, not a crawler.
"""

import argparse
import csv
import hashlib
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Identify ourselves honestly; a few vendor CDNs refuse the default urllib agent.
USER_AGENT = "ragline-fetch-corpus/0.1 (+https://github.com/14MM47/ragline)"


def load_manifest(path: Path) -> list[dict]:
    """Read manifest.csv into a list of row dicts."""
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def select_rows(rows: list[dict], categories: list[str] | None, golden_only: bool) -> list[dict]:
    """Apply the --category / --golden-only filters."""
    wanted = {c.lower() for c in categories} if categories else None
    selected = []
    for row in rows:
        if wanted is not None and row["category"].lower() not in wanted:
            continue
        if golden_only and not row.get("golden_questions"):
            continue
        selected.append(row)
    return selected


def safe_target(dest: Path, rel_path: str) -> Path:
    """Resolve a manifest path under dest, refusing anything that escapes it.

    The manifest is a file in a git repo, but a path is still input: a row
    containing "../" must not be able to write outside the corpus directory.
    """
    target = (dest / rel_path).resolve()
    if dest.resolve() not in target.parents:
        raise ValueError(f"manifest path escapes the destination: {rel_path}")
    return target


def sha256_of(path: Path) -> str:
    """Streamed SHA-256 of a file on disk."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, target: Path, timeout: float) -> str:
    """Stream url to target (via a .part file); return the SHA-256 of what arrived.

    Raises ValueError when the response is not a PDF — vendor sites answer a
    moved document with a 200 HTML page at least as often as with a 404.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    first = b""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, part.open("wb") as fh:
            for block in iter(lambda: response.read(1 << 16), b""):
                if not first:
                    first = block[:5]
                digest.update(block)
                fh.write(block)
        if first != b"%PDF-":
            raise ValueError("response is not a PDF (moved, or behind a login)")
        # Atomic within one filesystem: a half-written file never takes the real name.
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)
    return digest.hexdigest()


def fetch_row(row: dict, dest: Path, timeout: float, dry_run: bool, force: bool = False) -> str:
    """Bring one document into place. Returns a status word:

    present | differs | fetched | changed | no-url | would-fetch | failed:<why>
    """
    target = safe_target(dest, row["path"])
    if target.is_file():
        # Already there and intact: nothing to do (this is what makes re-runs cheap).
        if sha256_of(target) == row["sha256"]:
            return "present"
        # There but different — a revision fetched earlier, or a copy placed by
        # hand. Never overwrite someone's file unless asked to.
        if not force:
            return "differs"
    if not row.get("source_url"):
        return "no-url"
    if dry_run:
        return "would-fetch"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        got = download(row["source_url"], target, timeout)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        # Keep the reason short and free of the URL's query string.
        reason = getattr(exc, "reason", None) or getattr(exc, "code", None) or exc
        return f"failed:{reason}"
    return "fetched" if got == row["sha256"] else "changed"


def main() -> int:
    """Parse args, fetch the selected rows, print a summary."""
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Download the test corpus listed in eval/corpus/manifest.csv")
    parser.add_argument("--manifest", default=str(repo / "eval" / "corpus" / "manifest.csv"), help="Manifest to read")
    parser.add_argument(
        "--dest",
        default=os.getenv("RAGLINE_CORPUS_DIR", "testdata"),
        help="Corpus root to fill (default: $RAGLINE_CORPUS_DIR or ./testdata)",
    )
    parser.add_argument("--category", action="append", help="Only this category (repeatable), e.g. --category hmi")
    parser.add_argument("--golden-only", action="store_true", help="Only documents cited by the golden set")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be fetched; download nothing")
    parser.add_argument(
        "--force", action="store_true", help="Re-download files that exist but differ from the manifest"
    )
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds to pause between downloads (default 1.0)")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-request timeout in seconds (default 120)")
    args = parser.parse_args()

    rows = select_rows(load_manifest(Path(args.manifest)), args.category, args.golden_only)
    if not rows:
        print("nothing selected — check --category against the manifest's category column")
        return 1
    dest = Path(args.dest).expanduser()
    total_mb = sum(int(r["size_bytes"]) for r in rows) / 1e6
    print(f"{len(rows)} documents selected ({total_mb:,.0f} MB) -> {dest.resolve()}")

    outcomes: dict[str, list[dict]] = {}
    for i, row in enumerate(rows, start=1):
        status = fetch_row(row, dest, args.timeout, args.dry_run, args.force)
        outcomes.setdefault(status.split(":", 1)[0], []).append({**row, "status": status})
        print(f"[{i}/{len(rows)}] {status:<12} {row['path']}")
        # Pause only after a real request, so skipping present files stays instant.
        if status.split(":", 1)[0] in ("fetched", "changed", "failed") and i < len(rows):
            time.sleep(args.delay)

    print("\nsummary: " + ", ".join(f"{len(v)} {k}" for k, v in sorted(outcomes.items())))
    # The three outcomes a person has to act on, with enough detail to act.
    for row in outcomes.get("changed", []) + outcomes.get("differs", []):
        print(f"  {row['status']} (kept; digest differs from the evaluated copy): {row['path']}")
    for row in outcomes.get("failed", []):
        print(f"  {row['status']}: {row['path']}  <{row['source_url']}>")
    for row in outcomes.get("no-url", []):
        print(f"  no URL recorded: {row['path']}  title={row['title']!r}  sha256={row['sha256'][:16]}…")
    # Non-zero only for network failures: missing URLs are a known property of
    # the manifest, and a changed digest still leaves a usable document.
    return 1 if outcomes.get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
