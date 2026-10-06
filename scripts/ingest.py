"""ingest.py — bulk-ingest a local directory tree from the command line.

Walks a directory, uploads every supported file into the ingestion pipeline
(exactly as the batch API would), and waits for completion. The
--original-base flag records each file's original network location so
citations can point back to it:

    python scripts/ingest.py testdata/vfd --original-base '\\\\server\\eng\\vfd'

Requires Qdrant running and a configured .env (LLM key needed only when
ENABLE_KNOWLEDGE_GRAPH=true).
"""

import argparse
import asyncio
import hashlib
import sys
import time
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, "src")

from ragline.parsing.registry import supported_extensions  # noqa: E402


async def main() -> int:
    """Parse args, enqueue every supported file, run the batch, report."""
    parser = argparse.ArgumentParser(description="Bulk-ingest a directory of documents")
    parser.add_argument("directory", help="Directory to ingest (recursively)")
    parser.add_argument(
        "--original-base",
        default="",
        help="Original network base path recorded per file (e.g. \\\\server\\share\\project)",
    )
    parser.add_argument(
        "--no-graph",
        action="store_true",
        help="Skip knowledge-graph extraction for this run (faster, cheaper)",
    )
    args = parser.parse_args()

    root = Path(args.directory).expanduser().resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory")
        return 1

    # Imports deferred until after arg parsing so --help stays instant.
    from ragline.api.dependencies import (
        get_embedder,
        get_file_store,
        get_llm,
        get_retrieval_pipeline,
        get_vector_store,
    )
    from ragline.config import settings
    from ragline.ingestion.worker import BatchWorker
    from ragline.storage.metadata_db import create_batch, create_document, get_batch, init_db
    from ragline.storage.paths import join_original_path

    # Ensure tables exist when running against a fresh data dir.
    await init_db()

    # Collect every supported file below the root, stable order.
    supported = set(supported_extensions())
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in supported
    )
    if not files:
        print(f"no supported files found under {root} (supported: {sorted(supported)})")
        return 1
    print(f"found {len(files)} supported files under {root}")

    # One batch for the whole run; one Document row per file — mirroring the
    # batch upload API so downstream behaviour is identical.
    file_store = get_file_store()
    batch = await create_batch(total_files=len(files))

    for path in files:
        data = path.read_bytes()
        # Path of the file relative to the ingest root, POSIX-style —
        # matches what a ZIP of this directory would contain.
        rel_path = path.relative_to(root).as_posix()
        await file_store.save(f"{batch.id}/{rel_path}", data)
        await create_document(
            filename=f"{batch.id}/{rel_path}",
            file_type=path.suffix.lower().lstrip("."),
            file_hash=hashlib.sha256(data).hexdigest(),
            batch_id=batch.id,
            source_path=rel_path,
            original_path=join_original_path(args.original_base, rel_path) if args.original_base else "",
        )

    # Optionally suppress graph extraction for this run only.
    llm = None if args.no_graph else get_llm()
    worker = BatchWorker(
        file_store=file_store,
        embedder=get_embedder(),
        vector_store=get_vector_store(),
        pipeline=get_retrieval_pipeline(),
        llm=llm,
    )
    print(f"processing batch {batch.id} "
          f"(parallel={settings.batch_max_parallel}, graph={'off' if args.no_graph else 'on'})...")

    def _hms(seconds: float) -> str:
        """Seconds -> H:MM:SS, for the progress line's elapsed/ETA fields."""
        s = int(seconds)
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"

    async def report_progress() -> None:
        """Print done/total, rate and ETA every 30 s until cancelled.

        The worker logs one structlog line per finished document, which gives
        no sense of rate or remaining time over a multi-hour bulk run; this
        side task polls the batch counters the worker already maintains and
        prints a single glanceable line instead.
        """
        started = time.monotonic()
        while True:
            await asyncio.sleep(30)
            b = await get_batch(batch.id)
            # A document is "done" whatever its outcome — ok, failed or skipped.
            done = b.completed_files + b.failed_files + b.skipped_files
            elapsed = time.monotonic() - started
            rate = done / elapsed * 60 if elapsed else 0.0  # docs per minute
            # ETA only once at least one document has finished; "?" until then.
            eta = _hms((len(files) - done) / rate * 60) if rate else "?"
            print(
                f"progress: {done}/{len(files)} done "
                f"({b.completed_files} ok, {b.failed_files} failed, "
                f"{b.skipped_files} skipped) | elapsed {_hms(elapsed)} | "
                f"{rate:.1f} docs/min | ETA {eta}"
            )

    # Run the batch to completion in-process (no background task needed here),
    # with the progress reporter alongside; always cancel it when the batch ends.
    progress = asyncio.create_task(report_progress())
    try:
        await worker.process_batch(batch.id)
    finally:
        progress.cancel()

    # Report the final counters.
    final = await get_batch(batch.id)
    print(
        f"batch {final.status}: {final.completed_files} completed, "
        f"{final.failed_files} failed, {final.skipped_files} skipped (duplicates)"
    )
    return 0 if final.status == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
