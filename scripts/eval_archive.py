"""eval_archive.py — copy evaluation artefacts that are not in git to an archive location.

Two jobs (docs/eval/call-capture-plan.md, option B — transcripts stay out of git):

    # every rung (the campaign runner calls this after judging):
    python scripts/eval_archive.py transcripts eval/results/eval-2026-10 --dest /mnt/c/.../ragline-eval-archive

    # once, after the eval index is frozen:
    python scripts/eval_archive.py index --collection ragline_eval_v1 \\
        --db data/ragline_eval_v1.db --dest /mnt/c/.../ragline-eval-archive

`transcripts` copies every rN.transcripts.jsonl.gz under the campaign directory to
<dest>/<campaign>/<rung>/<condition>/, skipping files already archived with the
same SHA-256, and writes a checksum list. `index` takes a Qdrant snapshot of the
collection through its REST API and an online SQLite backup of the metadata /
knowledge-graph DB (consistent even while the DB is open), into
<dest>/index-<collection>-<date>/ with a digest of sizes and SHA-256s.
"""

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Allow running from the repo root without installing the package.
sys.path.insert(0, "src")

# Name pattern of the transcript sidecars written by scripts/evaluate.py.
TRANSCRIPT_GLOB = "*.transcripts.jsonl.gz"


def sha256(path: Path) -> str:
    """SHA-256 of a file, read in 1 MiB blocks (snapshots and DBs run to gigabytes)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def archive_transcripts(campaign_dir: Path, dest: Path) -> dict:
    """Copy the campaign's transcript sidecars to dest/<campaign>/...; returns counts."""
    target_root = dest / campaign_dir.name
    copied = skipped = 0
    sums: dict[str, str] = {}
    for src in sorted(campaign_dir.rglob(TRANSCRIPT_GLOB)):
        rel = src.relative_to(campaign_dir)
        target = target_root / rel
        digest = sha256(src)
        sums[rel.as_posix()] = digest
        # Already archived with identical content: nothing to do.
        if target.is_file() and sha256(target) == digest:
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        # Copy to a temp name, then rename, so a half-copied file never looks archived.
        tmp = target.with_name(target.name + ".part")
        shutil.copyfile(src, tmp)
        tmp.replace(target)
        copied += 1
    if sums:
        target_root.mkdir(parents=True, exist_ok=True)
        # The checksum list covers everything archived so far for this campaign.
        listing = target_root / "transcripts.sha256.json"
        existing = json.loads(listing.read_text()) if listing.is_file() else {}
        listing.write_text(json.dumps({**existing, **sums}, indent=1, sort_keys=True))
    return {"copied": copied, "already_archived": skipped, "total": len(sums), "dest": str(target_root)}


def snapshot_collection(base_url: str, collection: str, out: Path, client: httpx.Client | None = None) -> int:
    """Create a Qdrant snapshot of `collection` and stream it to `out`; returns bytes written."""
    if client is None:
        # Own the client (and close it) when the caller did not pass one.
        with httpx.Client(timeout=httpx.Timeout(30.0, read=1800.0)) as owned:
            return snapshot_collection(base_url, collection, out, owned)
    http = client
    # Qdrant writes the snapshot inside its own storage and returns its name.
    resp = http.post(f"{base_url}/collections/{collection}/snapshots", params={"wait": "true"})
    resp.raise_for_status()
    name = resp.json()["result"]["name"]
    written = 0
    tmp = out.with_name(out.name + ".part")
    try:
        with http.stream("GET", f"{base_url}/collections/{collection}/snapshots/{name}") as dl:
            dl.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in dl.iter_bytes(1 << 20):
                    fh.write(chunk)
                    written += len(chunk)
        tmp.replace(out)
    finally:
        # The copy inside Qdrant's storage is not needed once downloaded.
        http.delete(f"{base_url}/collections/{collection}/snapshots/{name}")
    return written


def backup_sqlite(db: Path, out: Path) -> int:
    """Consistent copy of a SQLite database (WAL included); returns bytes.

    Opened read-write (not ?mode=ro) so SQLite can recover a WAL left by an earlier
    writer; nothing is written to the data. Meant for a quiescent DB (the frozen eval
    index): with a busy concurrent writer the backup API restarts until it gets a
    clean pass.
    """
    tmp = out.with_name(out.name + ".part")
    src = sqlite3.connect(db)
    dst = sqlite3.connect(tmp)
    try:
        # sqlite's backup API copies page by page under the right locks.
        src.backup(dst, pages=4096)
    finally:
        dst.close()
        src.close()
    tmp.replace(out)
    return out.stat().st_size


def archive_index(collection: str, db: Path, dest: Path, base_url: str, client: httpx.Client | None = None) -> dict:
    """Snapshot the eval index (Qdrant collection + metadata DB) into dest; returns the digest."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = dest / f"index-{collection}-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    snap = folder / f"{collection}.snapshot"
    dbcopy = folder / db.name
    digest = {
        "collection": collection,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshot": {"file": snap.name, "bytes": snapshot_collection(base_url, collection, snap, client)},
        "db": {"file": dbcopy.name, "bytes": backup_sqlite(db, dbcopy)},
    }
    digest["snapshot"]["sha256"] = sha256(snap)
    digest["db"]["sha256"] = sha256(dbcopy)
    (folder / "digest.json").write_text(json.dumps(digest, indent=1))
    return digest


def main(argv: list[str] | None = None) -> int:
    """Parse args and run one archive job."""
    parser = argparse.ArgumentParser(description="Archive evaluation artefacts kept out of git")
    sub = parser.add_subparsers(dest="job", required=True)
    t = sub.add_parser("transcripts", help="Copy a campaign's transcript sidecars")
    t.add_argument("campaign_dir", help="e.g. eval/results/eval-2026-10")
    t.add_argument("--dest", required=True, help="Archive root (e.g. a Windows-drive folder)")
    i = sub.add_parser("index",
                       help="Snapshot the eval index (Qdrant collection + metadata DB; DB should be quiescent)")
    i.add_argument("--collection", required=True)
    i.add_argument("--db", required=True, help="SQLite metadata DB, e.g. data/ragline_eval_v1.db")
    i.add_argument("--dest", required=True)
    args = parser.parse_args(argv)

    dest = Path(args.dest)
    if args.job == "transcripts":
        campaign_dir = Path(args.campaign_dir)
        if not campaign_dir.is_dir():
            print(f"error: {campaign_dir} is not a directory")
            return 1
        print(json.dumps(archive_transcripts(campaign_dir, dest)))
        return 0

    db = Path(args.db)
    if not db.is_file():
        print(f"error: {db} does not exist")
        return 1
    from ragline.config import settings

    base_url = f"http://{settings.qdrant_host}:{settings.qdrant_port}"
    print(json.dumps(archive_index(args.collection, db, dest, base_url), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
