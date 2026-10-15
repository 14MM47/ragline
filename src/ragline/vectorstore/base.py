"""BaseVectorStore — the interface the retrieval pipeline talks to.

Ported from raggles minus the sparse/visual extension points (ragline's
sparse search is the in-process BM25 index; ColPali is not ported). The
abstraction survives so a different store could replace Qdrant when scaling.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ragline.chunking.models import Chunk


@dataclass
class SearchResult:
    """One search hit: the reconstructed chunk plus its similarity score."""

    chunk: Chunk
    score: float


class BaseVectorStore(ABC):
    async def count(self) -> int | None:
        """Number of stored chunks, or None when the backend cannot say.

        Used by the evaluation harness to fingerprint the index a run used;
        not part of the serving path, hence a default rather than abstract.
        """
        return None

    @abstractmethod
    async def upsert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Store chunks with their dense embeddings (idempotent by chunk id)."""
        ...

    @abstractmethod
    async def search_filtered(
        self,
        embedding: list[float],
        top_k: int = 10,
        allowed_document_ids: list[str] | None = None,
        excluded_source_files: list[str] | None = None,
    ) -> list[SearchResult]:
        """Dense similarity search with optional server-side filters."""
        ...

    @abstractmethod
    async def delete_by_document_id(self, document_id: str) -> None:
        """Remove every chunk belonging to one document."""
        ...

    async def get_chunks_by_position(self, wanted: list[tuple[str, int]]) -> list[Chunk]:
        """Chunks by (document_id, chunk_index) — used to add a hit's neighbour.

        Default: none (stores without the lookup simply skip neighbour expansion).
        """
        return []

    @abstractmethod
    async def get_all_chunks(self) -> list[Chunk]:
        """Return all chunks (used for the BM25 index rebuild at startup)."""
        ...

    @abstractmethod
    async def ping(self, timeout: float = 2.0) -> bool:
        """Fast reachability check for the health endpoint (never raises)."""
        ...
