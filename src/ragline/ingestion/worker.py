"""Async batch ingestion worker with parallel document processing.

Ported from raggles with the playground stages removed (vision parsing,
parent-child, PII, propositions, contextual enrichment, ColPali, semantic
cache, entity dedup, community detection). The surviving per-document flow:

    dedup-by-hash -> parsing -> chunking -> embedding -> storing
    -> chunk records -> extracting_graph (flag-gated) -> ready

Concurrency model (unchanged from raggles):
  * documents within a batch run under an asyncio.Semaphore
    (settings.batch_max_parallel, default 3);
  * CPU-bound parsing/chunking runs in a ThreadPoolExecutor sized to
    cpu_count - 1, keeping the event loop responsive;
  * each document's `stage` field is updated live for the BatchProgress UI.
"""

import asyncio
import functools
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import structlog

from ragline.chunking.structural import chunk_document
from ragline.config import settings
from ragline.embeddings.base import BaseEmbedder
from ragline.llm.base import BaseLLM
from ragline.parsing.registry import get_parser
from ragline.storage.file_store import BaseFileStore
from ragline.storage.metadata_db import (
    find_document_by_hash,
    get_batch_documents,
    increment_batch_counter,
    save_chunk_records,
    update_batch,
    update_document,
)
from ragline.vectorstore.base import BaseVectorStore

log = structlog.get_logger()

# Use all cores except one (reserved for the OS scheduler and system tasks).
# Each parse/OCR job runs single-threaded (OMP_THREAD_LIMIT=1 in pdf_parser),
# so total CPU threads at saturation = cpu_count - 1.
_safe_workers = max(1, (os.cpu_count() or 2) - 1)
_parse_executor = ThreadPoolExecutor(max_workers=_safe_workers)

# Strong references to fire-and-forget batch tasks: asyncio only holds a weak
# reference to running tasks, so an unreferenced task can be garbage-collected
# mid-ingestion.
_background_tasks: set[asyncio.Task] = set()


def spawn_background(coro) -> asyncio.Task:
    """Schedule a background task and keep it referenced until it finishes."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def _parse_document(file_path_str: str):
    """Parse a document in a worker thread, keeping the event loop free."""
    file_path = Path(file_path_str)
    parser = get_parser(file_path)
    return parser.parse(file_path)


class BatchWorker:
    def __init__(
        self,
        file_store: BaseFileStore,
        embedder: BaseEmbedder,
        vector_store: BaseVectorStore,
        pipeline=None,
        llm: BaseLLM | None = None,
        max_parallel: int | None = None,
    ):
        # Injected collaborators (built by api/dependencies.py).
        self.file_store = file_store
        self.embedder = embedder
        self.vector_store = vector_store
        # RetrievalPipeline, optional so ingestion works without retrieval
        # wiring and in tests; when present, its BM25 index is rebuilt post-batch.
        self.pipeline = pipeline
        # LLM used only for knowledge-graph extraction (flag-gated below).
        self.llm = llm
        # Cap on concurrently processing documents within this batch.
        self.max_parallel = max_parallel or settings.batch_max_parallel
        self._semaphore = asyncio.Semaphore(self.max_parallel)

    async def process_batch(self, batch_id: str) -> None:
        """Process all pending documents in a batch, then finalize its status."""
        await update_batch(batch_id, status="processing")

        # Only documents still pending are processed (idempotent re-runs).
        docs = await get_batch_documents(batch_id)
        pending = [d for d in docs if d.status == "pending"]

        # Fan out; the semaphore inside _process_document enforces the cap.
        tasks = [self._process_document(batch_id, doc) for doc in pending]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # _process_document handles its own errors; anything surfacing here
        # is unexpected and worth logging loudly.
        for doc, result in zip(pending, results):
            if isinstance(result, Exception):
                log.error(
                    "unexpected batch error",
                    batch_id=batch_id,
                    document_id=doc.id,
                    error=str(result),
                )

        # Rebuild the in-memory BM25 index ONCE per batch, not per document.
        if self.pipeline is not None:
            try:
                await self.pipeline.rebuild_bm25_index()
            except Exception as e:
                log.error("bm25 rebuild failed", batch_id=batch_id, error=str(e))

        # Final batch status reflects whether any document errored.
        docs = await get_batch_documents(batch_id)
        has_errors = any(d.status == "error" for d in docs)
        status = "completed_with_errors" if has_errors else "completed"
        await update_batch(batch_id, status=status)

        log.info("batch completed", batch_id=batch_id, status=status)

    async def _process_document(self, batch_id: str, doc) -> None:
        """Run one document through the full ingestion flow (bounded by the semaphore)."""
        async with self._semaphore:
            try:
                # --- dedup: identical bytes already ingested? -------------
                # Skip the check for explicit new-version uploads: a new
                # version with bytes identical to its predecessor is
                # intentional (e.g. a provenance-only correction) and must NOT
                # be dropped as a duplicate, or the version chain stalls.
                if doc.file_hash and not doc.previous_version_id:
                    existing = await find_document_by_hash(doc.file_hash)
                    if existing and existing.id != doc.id:
                        # Mark skipped; the stored copy stays for provenance.
                        await update_document(doc.id, status="skipped_duplicate")
                        await increment_batch_counter(batch_id, "skipped_files")
                        log.info(
                            "skipped duplicate",
                            document_id=doc.id,
                            duplicate_of=existing.id,
                        )
                        return

                await update_document(doc.id, status="processing", stage="parsing")

                # --- parse (CPU-bound, in the thread pool) ----------------
                # Document.filename holds the full storage path
                # ("{batch_id}/{rel_path}") — resolve it in the file store.
                file_path = await self.file_store.get_path(doc.filename)
                loop = asyncio.get_event_loop()
                parsed = await loop.run_in_executor(
                    _parse_executor, _parse_document, str(file_path)
                )

                # --- chunk (also CPU-bound: tiktoken encoding) ------------
                await update_document(doc.id, stage="chunking")
                chunks = await loop.run_in_executor(
                    _parse_executor,
                    functools.partial(chunk_document, parsed, document_id=doc.id),
                )

                # --- embed ------------------------------------------------
                await update_document(doc.id, stage="embedding")
                texts = [c.text for c in chunks]
                embeddings = await self.embedder.embed(texts)

                # --- store vectors + payload in Qdrant --------------------
                await update_document(doc.id, stage="storing")
                await self.vector_store.upsert_chunks(chunks, embeddings)

                # --- mirror chunk coordinates into SQLite -----------------
                await save_chunk_records(doc.id, chunks)

                # --- knowledge graph extraction (flag-gated) --------------
                if settings.enable_knowledge_graph and self.llm:
                    try:
                        await update_document(doc.id, stage="extracting_graph")
                        from ragline.knowledge_graph.extractor import extract_entities_and_relationships
                        from ragline.knowledge_graph.store import save_entities, save_relationships

                        # LLM reads every chunk and emits entities + relations.
                        raw_entities, raw_rels = await extract_entities_and_relationships(
                            chunks, self.llm, embedder=self.embedder
                        )
                        saved_entities = await save_entities(raw_entities)
                        await save_relationships(raw_rels, saved_entities)
                        log.info(
                            "knowledge graph extracted",
                            document_id=doc.id,
                            entities=len(raw_entities),
                            relationships=len(raw_rels),
                        )
                    except Exception as e:
                        # KG failure never fails the document — retrieval
                        # still works without graph context.
                        log.warning("knowledge graph extraction failed", error=str(e))

                # --- done -------------------------------------------------
                await update_document(
                    doc.id,
                    page_count=len(parsed.pages),
                    chunk_count=len(chunks),
                    status="ready",
                    stage="",
                )
                await increment_batch_counter(batch_id, "completed_files")

                log.info(
                    "document ingested",
                    batch_id=batch_id,
                    document_id=doc.id,
                    filename=doc.filename,
                    pages=len(parsed.pages),
                    chunks=len(chunks),
                )

            except Exception as e:
                # Any failure marks THIS document errored; the batch continues.
                await update_document(doc.id, status="error")
                await increment_batch_counter(batch_id, "failed_files")
                log.error(
                    "document ingestion failed",
                    batch_id=batch_id,
                    document_id=doc.id,
                    filename=doc.filename,
                    error=str(e),
                )
