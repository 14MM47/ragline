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

    @abstractmethod
    async def get_all_chunks(self) -> list[Chunk]:
        """Return all chunks (used for the BM25 index rebuild at startup)."""
        ...

    @abstractmethod
    async def ping(self, timeout: float = 2.0) -> bool:
        """Fast reachability check for the health endpoint (never raises)."""
        ...
