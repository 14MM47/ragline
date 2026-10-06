"""build_corpus_index.py — write the public index of the (unpublished) test corpus.

The corpus ragline is evaluated on is ~800 vendor datasheets and manuals. They
are freely downloadable but copyrighted, so the PDFs are NOT in this repo.
This script records everything about them that CAN be published — where each
file sits in the corpus tree, what it is, how big, its SHA-256, and the public
URL it was fetched from — so the golden question sets (which name documents by
corpus-relative path) make sense, and so the corpus can be rebuilt with
scripts/fetch_corpus.py.

Outputs (both committed):

    eval/corpus/manifest.csv   one row per document, machine-readable
    eval/corpus/INDEX.md       summary + the HMI documents, cross-referenced
                               to the golden questions that cite them

Usage (maintainer, with the PDFs on disk):

    python scripts/build_corpus_index.py --corpus-dir ../testdata

Source URLs come from a fetch log (TSV: path, sha256, size, url) kept beside
the PDFs; rows the log does not cover keep whatever URL the existing
manifest.csv already has, so re-running never loses a URL.
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Column order of manifest.csv — fetch_corpus.py and the tests read by name.
COLUMNS = [
    "path",              # corpus-relative, forward slashes: <category>/<vendor>/<family>/<file>.pdf
    "category",          # first path segment (hmi, plc, vfd, ...)
    "vendor",            # second path segment
    "product_family",    # third path segment ("" when the file sits directly under the vendor)
    "title",             # the PDF's own metadata title ("" when the vendor left it empty)
    "pages",             # page count
    "size_bytes",        # exact file size
    "sha256",            # hex digest of the file as evaluated
    "source_url",        # public URL it was fetched from ("" = not recorded)
    "golden_questions",  # space-separated ids from the golden set that cite this file
]

# Query parameters that are per-download signatures, not part of the address.
# The document resolves without them, and a stale signature only invites a 403.
_SIGNATURE_PARAMS = {"x-sign"}


def clean_url(url: str) -> str:
    """Normalise one fetch-log URL for publication.

    Anything that is not an http(s) URL (the log marks files that predate it
    with a placeholder word) becomes "", and signature query parameters are
    dropped. Everything else is returned untouched — vendors' cache-busting
    `?v=` style parameters are part of how the file is actually served.
    """
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return ""
    parts = urlsplit(url)
    # keep_blank_values so "?download" style flags survive the round trip.
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _SIGNATURE_PARAMS]
    if len(kept) == len(parse_qsl(parts.query, keep_blank_values=True)):
        return url  # nothing stripped: return byte-identical, no re-encoding
    return urlunsplit(parts._replace(query=urlencode(kept)))


def split_path(rel_path: str) -> tuple[str, str, str]:
    """(category, vendor, product_family) from a corpus-relative path.

    The tree is <category>/<vendor>/<family>/<file>; shallower files simply
    leave the missing levels empty rather than failing.
    """
    parts = rel_path.split("/")
    category = parts[0] if len(parts) > 1 else ""
    vendor = parts[1] if len(parts) > 2 else ""
    family = parts[2] if len(parts) > 3 else ""
    return category, vendor, family


def golden_references(golden_paths: list[Path]) -> dict[str, list[str]]:
    """Map corpus path -> ids of the golden questions that list it as a source."""
    refs: dict[str, list[str]] = defaultdict(list)
    for golden in golden_paths:
        for item in json.loads(golden.read_text(encoding="utf-8")):
            qid = item.get("id")
            if not qid:
                continue  # sets without ids (the unreviewed draft) can't be cross-referenced
            for source in item.get("expected_sources", []):
                refs[source].append(qid)
    return refs


def read_fetch_log(path: Path) -> dict[str, dict]:
    """Parse the fetch log (TSV, no header: path, sha256, size, url)."""
    rows: dict[str, dict] = {}
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = line.split("\t")
        if len(cells) != 4:
            continue  # tolerate blank/short lines rather than abort the whole index
        rows[cells[0]] = {"sha256": cells[1], "size_bytes": int(cells[2]), "source_url": clean_url(cells[3])}
    return rows


def read_existing_urls(manifest: Path) -> dict[str, str]:
    """URLs already published in manifest.csv, so a re-run never drops one."""
    if not manifest.is_file():
        return {}
    with manifest.open(newline="", encoding="utf-8") as fh:
        return {row["path"]: row.get("source_url", "") for row in csv.DictReader(fh)}


def sha256_of(path: Path) -> str:
    """Streamed SHA-256 (the big manuals are hundreds of MB)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def pdf_facts(path: Path) -> tuple[int, str]:
    """(page count, metadata title) straight from the PDF."""
    import pymupdf as fitz  # already a ragline dependency; deferred so --help stays instant

    with fitz.open(path) as doc:
        title = (doc.metadata or {}).get("title") or ""
        # Collapse stray whitespace/newlines so the CSV stays one line per document.
        return doc.page_count, " ".join(title.split())


def build_rows(corpus_dir: Path, fetch_log: dict[str, dict], known_urls: dict[str, str],
               refs: dict[str, list[str]]) -> list[dict]:
    """One manifest row per PDF under corpus_dir, sorted by path."""
    rows = []
    pdfs = sorted(p for p in corpus_dir.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")
    for pdf in pdfs:
        rel = pdf.relative_to(corpus_dir).as_posix()
        logged = fetch_log.get(rel, {})
        size = pdf.stat().st_size
        # A revised PDF can have exactly the same size as the fetched copy.
        # The manifest describes the bytes on disk; always hash those bytes.
        sha = sha256_of(pdf)
        category, vendor, family = split_path(rel)
        pages, title = pdf_facts(pdf)
        rows.append({
            "path": rel,
            "category": category,
            "vendor": vendor,
            "product_family": family,
            "title": title,
            "pages": pages,
            "size_bytes": size,
            "sha256": sha,
            # The fetch log wins; fall back to a URL published by an earlier run.
            "source_url": logged.get("source_url") or known_urls.get(rel, ""),
            "golden_questions": " ".join(refs.get(rel, [])),
        })
    return rows


def write_manifest(rows: list[dict], out: Path) -> None:
    """Write manifest.csv (LF line endings so the diff is stable across OSes)."""
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _md(text: str) -> str:
    """Escape the one character that breaks a Markdown table cell."""
    return str(text).replace("|", "\\|")


def render_index(rows: list[dict], highlight: str) -> str:
    """INDEX.md: per-category summary, then the highlighted category in full."""
    lines = [
        "# Corpus index",
        "",
        "<!-- GENERATED by scripts/build_corpus_index.py — edit the script, not this file. -->",
        "",
        f"{len(rows)} documents, {sum(r['pages'] for r in rows):,} pages, "
        f"{sum(r['size_bytes'] for r in rows) / 1e9:.1f} GB. The PDFs themselves are not in this "
        "repository — see [README.md](README.md) for why, and for how to fetch them.",
        "",
        "## By category",
        "",
        "| Category | Documents | Pages | Size (MB) | Vendors | With source URL | Cited by golden set |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    by_category: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)
    for category in sorted(by_category):
        group = by_category[category]
        name = f"**{category}**" if category == highlight else category
        lines.append(
            f"| {name} | {len(group)} | {sum(r['pages'] for r in group):,} "
            f"| {sum(r['size_bytes'] for r in group) / 1e6:,.0f} "
            f"| {len({r['vendor'] for r in group})} "
            f"| {sum(1 for r in group if r['source_url'])} "
            f"| {sum(1 for r in group if r['golden_questions'])} |"
        )
    lines += [
        "",
        "Every document, in every category, is listed in [manifest.csv](manifest.csv) "
        "(GitHub renders it as a searchable table).",
        "",
        f"## `{highlight}/` — the evaluated subset",
        "",
        "The recorded evaluation runs ingested exactly this category, and "
        "[`eval/golden_set_hmi.json`](../golden_set_hmi.json) asks its questions about it. "
        "**Golden Qs** lists the question ids whose `expected_sources` include the document; "
        "documents with none are still in the index the answers were retrieved from — they are "
        "the distractors.",
        "",
    ]
    by_vendor: dict[str, list[dict]] = defaultdict(list)
    for row in by_category.get(highlight, []):
        by_vendor[row["vendor"]].append(row)
    for vendor in sorted(by_vendor):
        group = by_vendor[vendor]
        lines += [
            f"### {vendor} ({len(group)})",
            "",
            "| Product family | File | Title (PDF metadata) | Pages | Golden Qs | Source |",
            "|---|---|---|---:|---|---|",
        ]
        for row in group:
            filename = row["path"].rsplit("/", 1)[-1]
            source = f"[link]({row['source_url']})" if row["source_url"] else "—"
            lines.append(
                f"| {_md(row['product_family'])} | `{_md(filename)}` | {_md(row['title']) or '—'} "
                f"| {row['pages']} | {row['golden_questions'] or '—'} | {source} |"
            )
        lines.append("")
    # Vendor/family breakdown for the rest, so the shape of the corpus is visible
    # without opening the CSV.
    lines += ["## Other categories — vendors and product families", ""]
    for category in sorted(by_category):
        if category == highlight:
            continue
        families: Counter = Counter((r["vendor"], r["product_family"]) for r in by_category[category])
        vendors: dict[str, list[str]] = defaultdict(list)
        for (vendor, family), count in sorted(families.items()):
            vendors[vendor].append(f"{family or '(top level)'} ({count})")
        lines += [f"### {category} ({len(by_category[category])})", ""]
        lines += [f"- **{vendor}** — {', '.join(items)}" for vendor, items in sorted(vendors.items())]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    """Parse args, read the PDFs, write manifest.csv + INDEX.md."""
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Build the public index of the test corpus (eval/corpus/)")
    parser.add_argument(
        "--corpus-dir",
        default=os.getenv("RAGLINE_CORPUS_DIR", "testdata"),
        help="Root of the PDF tree (default: $RAGLINE_CORPUS_DIR or ./testdata)",
    )
    parser.add_argument(
        "--fetch-log",
        default=None,
        help="TSV of path/sha256/size/url written when the corpus was fetched "
             "(default: <corpus-dir>/.fetch_manifest.tsv; optional)",
    )
    parser.add_argument(
        "--golden",
        action="append",
        default=None,
        help="Golden set(s) to cross-reference; repeatable (default: eval/golden_set_hmi.json)",
    )
    parser.add_argument("--out-dir", default=str(repo / "eval" / "corpus"), help="Where to write the index")
    parser.add_argument("--highlight", default="hmi", help="Category listed in full in INDEX.md (default: hmi)")
    args = parser.parse_args()

    corpus_dir = Path(args.corpus_dir).expanduser().resolve()
    if not corpus_dir.is_dir():
        print(f"error: {corpus_dir} is not a directory")
        return 1
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.csv"

    fetch_log = read_fetch_log(Path(args.fetch_log) if args.fetch_log else corpus_dir / ".fetch_manifest.tsv")
    golden_paths = [Path(g) for g in (args.golden or [repo / "eval" / "golden_set_hmi.json"])]
    rows = build_rows(corpus_dir, fetch_log, read_existing_urls(manifest), golden_references(golden_paths))
    if not rows:
        print(f"error: no PDFs found under {corpus_dir}")
        return 1

    write_manifest(rows, manifest)
    (out_dir / "INDEX.md").write_text(render_index(rows, args.highlight), encoding="utf-8")

    # A golden source that is not in the corpus is a typo in the question set —
    # surface it here rather than as a mystery miss in an evaluation run.
    known = {row["path"] for row in rows}
    orphans = sorted(src for src in golden_references(golden_paths) if src not in known)
    print(f"wrote {manifest} ({len(rows)} documents, {sum(1 for r in rows if r['source_url'])} with a source URL)")
    print(f"wrote {out_dir / 'INDEX.md'}")
    for src in orphans:
        print(f"warning: golden set cites a document that is not in the corpus: {src}")
    return 1 if orphans else 0


if __name__ == "__main__":
    sys.exit(main())
