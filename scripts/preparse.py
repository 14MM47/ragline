"""preparse.py — parse a directory tree into the parse cache, ahead of ingestion.

Parsing needs only CPU; embedding and KG extraction need the GPU pod. Run this
first (no pod, no Qdrant, no database), then ingest with the same
PARSE_CACHE_DIR and the pod spends its time on embedding and extraction only:

    python scripts/preparse.py testdata/hmi --cache-dir ./data/parse_cache --workers 5
    PARSE_CACHE_DIR=./data/parse_cache python scripts/ingest.py testdata/hmi

Each file is parsed in its own process (pymupdf4llm holds the GIL, so threads
would share about two cores). Files already cached under the current parser
fingerprint are skipped, so an interrupted run resumes where it stopped.
Largest files go first so the long parses overlap rather than trail at the end.
"""

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, "src")

from ragline.parsing.cache import ParseCache, file_sha256, fingerprint, ocr_engine, parser_identity  # noqa: E402
from ragline.parsing.registry import get_parser, supported_extensions  # noqa: E402


def _quiet_logs() -> None:
    """Keep worker processes to warnings and errors (one parse line each is noise at scale)."""
    import logging

    import structlog

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))


def parse_one(path_str: str, sha: str, cache_root: str, identity: dict) -> tuple[str, float]:
    """Parse one file into the cache (runs in a worker process); returns (path, seconds)."""
    _quiet_logs()
    path = Path(path_str)
    # The parent's identity, so every process writes into the same namespace.
    cache = ParseCache(cache_root, identity)
    started = time.monotonic()
    cache.put(sha, get_parser(path).parse(path))
    return path_str, time.monotonic() - started


def _hms(seconds: float) -> str:
    """Seconds -> H:MM:SS for the progress line."""
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def main(argv: list[str] | None = None) -> int:
    """Parse args, skip cached files, parse the rest in a process pool, report."""
    parser = argparse.ArgumentParser(description="Parse a directory tree into the parse cache")
    parser.add_argument("directory", help="Directory to parse (recursively)")
    parser.add_argument("--cache-dir", default=None, help="Cache root (default: PARSE_CACHE_DIR)")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                        help="Parallel parse processes (default: cores - 1)")
    parser.add_argument("--allow-no-ocr", action="store_true",
                        help="Parse even though OCR is enabled but Tesseract is missing")
    args = parser.parse_args(argv)

    from ragline.config import settings

    cache_root = args.cache_dir or settings.parse_cache_dir
    if not cache_root:
        print("error: no cache directory (pass --cache-dir or set PARSE_CACHE_DIR)")
        return 1
    root = Path(args.directory).expanduser().resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory")
        return 1

    # OCR on but no Tesseract here: scanned pages would be cached without text.
    # The fingerprint keeps such parses apart from OCR-capable ones, but the run
    # is almost certainly a mistake, so it stops unless explicitly allowed.
    if settings.enable_ocr_fallback and ocr_engine() == "absent" and not args.allow_no_ocr:
        print("error: ENABLE_OCR_FALLBACK is on but Tesseract is not available here; scanned pages "
              "would be cached without text. Install the [ocr] extra + tesseract, or pass --allow-no-ocr.")
        return 1

    # One identity for the whole run, computed here and handed to every worker.
    identity = parser_identity()
    cache = ParseCache(cache_root, identity)
    supported = set(supported_extensions())
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in supported)
    # Content hashes decide what is already cached (same bytes = same parse).
    todo = [(p, sha) for p in files if not cache.has(sha := file_sha256(p))]
    todo.sort(key=lambda item: -item[0].stat().st_size)
    print(f"cache {cache.dir} (fingerprint {fingerprint(identity)}): {len(files)} files, "
          f"{len(files) - len(todo)} already cached, {len(todo)} to parse with {args.workers} processes")
    if not todo:
        return 0

    started = time.monotonic()
    failed = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(parse_one, str(p), sha, str(cache_root), identity): p for p, sha in todo}
        for done, future in enumerate(as_completed(futures), 1):
            path = futures[future]
            try:
                _, secs = future.result()
                status = f"parsed in {secs:.0f}s"
            except Exception as exc:
                # One bad file is reported and skipped; ingest will parse (and fail) it itself.
                failed += 1
                status = f"FAILED: {type(exc).__name__}: {exc}"
            elapsed = time.monotonic() - started
            # Rate in files/min; the ETA is rough because files differ wildly in size.
            rate = done / elapsed * 60 if elapsed else 0.0
            eta = _hms((len(todo) - done) / rate * 60) if rate else "?"
            print(f"{done}/{len(todo)} {path.relative_to(root)}: {status} | elapsed {_hms(elapsed)} | ETA {eta}",
                  flush=True)
    print(f"done: {len(todo) - failed} parsed, {failed} failed, in {_hms(time.monotonic() - started)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
