"""QdrantVectorStore — dense chunk vectors + full source payload in Qdrant.

Ported from raggles with the playground branches removed: no BGE-M3 named
dense+sparse vectors (sparse search is the in-process BM25 index), no ColPali
visual collection, no parent-chunk zero vectors.

One improvement over raggles: the collection is created lazily on first
upsert using the ACTUAL embedding length, instead of a hardcoded dimension
table. Switching embedding models therefore needs no code change — but it
DOES need a fresh collection (vectors of different dimensions cannot mix);
change QDRANT_COLLECTION or delete the old one when swapping models.

The payload stored per point carries the chunk's complete source identity —
this is what makes citations "hard": the identity returned by search is
byte-for-byte what ingestion wrote, never LLM-generated.
"""

import asyncio
import uuid

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

from ragline.chunking.models import Chunk
from ragline.config import settings
from ragline.vectorstore.base import BaseVectorStore, SearchResult

log = structlog.get_logger()


class QdrantVectorStore(BaseVectorStore):
    def __init__(self):
        # Synchronous client wrapped in asyncio.to_thread at call sites —
        # same proven pattern as raggles. check_compatibility=False avoids
        # a hard failure on minor client/server version skew.
        self._client = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            check_compatibility=False,
        )
        self._collection = settings.qdrant_collection

    # --- collection management ---------------------------------------------

    def _collection_exists(self) -> bool:
        """True when our collection already exists on the server."""
        return self._collection in [c.name for c in self._client.get_collections().collections]

    def _ensure_collection(self, dim: int) -> None:
        """Create the collection on first use, sized to the real vector length."""
        if not self._collection_exists():
            self._client.create_collection(
                collection_name=self._collection,
                # Cosine distance matches how the embedding models are trained.
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            log.info("created qdrant collection", name=self._collection, dim=dim)

    # --- writes -------------------------------------------------------------

    async def upsert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Store chunks with their embeddings and full source payload."""
        if not chunks:
            return
        # Lazily create the collection sized to the actual embedding length.
        await asyncio.to_thread(self._ensure_collection, len(embeddings[0]))

        points = []
        for chunk, embedding in zip(chunks, embeddings):
            # Stable ID when the chunk carries one; fresh UUID otherwise.
            point_id = chunk.chunk_id or str(uuid.uuid4())
            # THE citation payload: everything needed to rebuild the Chunk
            # (and hence the citation) verbatim at search time.
            payload = {
                "text": chunk.text,
                "source_file": chunk.source_file,
                "document_id": chunk.document_id,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "section_header": chunk.section_header,
                "chunk_index": chunk.chunk_index,
                "chunk_id": point_id,
            }
            points.append(PointStruct(id=point_id, vector=embedding, payload=payload))

        # Upsert in batches of 100 to bound request sizes.
        batch_size = 100
        for i in range(0, len(points), batch_size):
            await asyncio.to_thread(
                self._client.upsert,
                collection_name=self._collection,
                points=points[i : i + batch_size],
            )

        log.info("upserted chunks to qdrant", count=len(chunks))

    async def delete_by_document_id(self, document_id: str) -> None:
        """Delete every point whose payload document_id matches."""
        # No collection yet means nothing to delete.
        if not await asyncio.to_thread(self._collection_exists):
            log.info("collection does not exist, skipping qdrant delete", document_id=document_id)
            return
        await asyncio.to_thread(
            self._client.delete,
            collection_name=self._collection,
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
        )
        log.info("deleted chunks from qdrant", document_id=document_id)

    # --- reads --------------------------------------------------------------

    async def search_filtered(
        self,
        embedding: list[float],
        top_k: int = 10,
        allowed_document_ids: list[str] | None = None,
        excluded_source_files: list[str] | None = None,
    ) -> list[SearchResult]:
        """Dense search with optional server-side pre-filters.

        allowed_document_ids scopes retrieval to specific documents (used by
        chat's compound mode); excluded_source_files honours per-query
        exclusions from the pre-pass ("ignoring the ABB manual, ...").
        """
        # An empty index can't match anything.
        if not await asyncio.to_thread(self._collection_exists):
            return []
        query_filter = self._build_query_filter(
            allowed_document_ids=allowed_document_ids,
            excluded_source_files=excluded_source_files,
        )
        results = await asyncio.to_thread(
            self._client.query_points,
            collection_name=self._collection,
            query=embedding,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
        search_results = self._to_search_results(results.points)

        # Case-insensitive safety net: the server-side must_not above is exact
        # (case-sensitive) MatchValue, but the BM25 leg (and the pre-pass that
        # names files) compares with casefold(). Drop any excluded chunk whose
        # name differs only in case so the two legs never disagree and an
        # excluded document can't get cited. (rerank_k < top_k absorbs the
        # slight shrink in the rare case-mismatch path.)
        if excluded_source_files:
            excluded_cf = self._excluded_casefold(excluded_source_files)
            search_results = [
                r for r in search_results if r.chunk.source_file.casefold() not in excluded_cf
            ]
        return search_results

    async def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        """Fetch specific chunks by their Qdrant point IDs."""
        if not chunk_ids:
            return []
        try:
            points = await asyncio.to_thread(
                self._client.retrieve,
                collection_name=self._collection,
                ids=chunk_ids,
                with_payload=True,
            )
            return [self._payload_to_chunk(p.payload, str(p.id)) for p in points]
        except Exception as e:
            # Missing collection / bad ids degrade to "not found".
            log.warning("get_chunks_by_ids failed", error=str(e))
            return []

    async def get_all_chunks(self) -> list[Chunk]:
        """Scroll the whole collection — feeds the BM25 rebuild at startup.

        NOTE: loads every chunk into memory. Fine at test-corpus scale;
        flagged in the roadmap as the thing to replace (Qdrant sparse vectors
        or SQLite FTS5) when scaling toward the 12TB corpus.
        """
        if not await asyncio.to_thread(self._collection_exists):
            return []
        chunks: list[Chunk] = []
        offset = None
        # Page through the collection 100 points at a time.
        while True:
            points, next_offset = await asyncio.to_thread(
                self._client.scroll,
                collection_name=self._collection,
                limit=100,
                offset=offset,
                with_payload=True,
            )
            for point in points:
                chunks.append(self._payload_to_chunk(point.payload, str(point.id)))
            # A None offset means the scroll is exhausted.
            if next_offset is None:
                break
            offset = next_offset

        return chunks

    async def ping(self, timeout: float = 2.0) -> bool:
        """Fast reachability check for /health, reusing the shared client.

        Bounds the wait so a liveness probe returns quickly even when Qdrant is
        hung (the blocking call may still finish later in its worker thread).
        Never raises — a failure just means "not reachable".
        """
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._client.get_collections), timeout=timeout
            )
            return True
        except Exception as e:
            log.debug("qdrant ping failed", error=str(e))
            return False

    # --- helpers ------------------------------------------------------------

    @staticmethod
    def _payload_to_chunk(payload: dict, point_id: str) -> Chunk:
        """Rebuild a Chunk from a stored payload — the inverse of upsert."""
        return Chunk(
            text=payload["text"],
            source_file=payload["source_file"],
            document_id=payload["document_id"],
            page_start=payload["page_start"],
            page_end=payload["page_end"],
            char_start=payload["char_start"],
            char_end=payload["char_end"],
            section_header=payload.get("section_header", ""),
            chunk_index=payload.get("chunk_index", 0),
            chunk_id=payload.get("chunk_id", point_id),
        )

    @staticmethod
    def _to_search_results(points) -> list[SearchResult]:
        """Convert Qdrant points into SearchResults with rebuilt chunks."""
        return [
            SearchResult(
                chunk=QdrantVectorStore._payload_to_chunk(point.payload, str(point.id)),
                score=point.score,
            )
            for point in points
        ]

    @staticmethod
    def _expand_excluded(excluded_source_files: list[str]) -> set[str]:
        """Excluded names plus their bare basenames.

        The pre-pass may name either the full stored form ("vfd/abb/acs880.pdf")
        or just the basename ("acs880.pdf"), so match on both.
        """
        expanded = set(excluded_source_files)
        for source_file in excluded_source_files:
            basename = source_file.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            if basename:
                expanded.add(basename)
        return expanded

    @staticmethod
    def _excluded_casefold(excluded_source_files: list[str]) -> set[str]:
        """Casefolded exclusion set — mirrors the BM25 leg's compare exactly."""
        return {s.casefold() for s in QdrantVectorStore._expand_excluded(excluded_source_files)}

    @staticmethod
    def _build_query_filter(
        allowed_document_ids: list[str] | None,
        excluded_source_files: list[str] | None,
    ) -> Filter | None:
        """Translate the pipeline's scoping options into a Qdrant filter."""
        must: list[FieldCondition] = []
        must_not: list[FieldCondition] = []

        if allowed_document_ids is not None:
            if allowed_document_ids:
                # Restrict to any of the allowed documents.
                must.append(
                    FieldCondition(key="document_id", match=MatchAny(any=allowed_document_ids))
                )
            else:
                # An explicitly EMPTY allow-list must match nothing — use an
                # impossible value rather than dropping the condition.
                must.append(
                    FieldCondition(key="document_id", match=MatchValue(value="__none__"))
                )

        if excluded_source_files:
            # Server-side must_not is an exact (case-sensitive) match; it is a
            # fast pre-filter. Case-differing names are caught by the casefold
            # post-filter in search_filtered (see _excluded_casefold).
            for source_file in sorted(QdrantVectorStore._expand_excluded(excluded_source_files)):
                must_not.append(
                    FieldCondition(key="source_file", match=MatchValue(value=source_file))
                )

        # No conditions at all -> no filter object.
        if not must and not must_not:
            return None
        return Filter(must=must or None, must_not=must_not or None)
