"""BaseEmbedder — abstract interface for embedding providers.

Ported from raggles minus the HybridEmbedder extension (BGE-M3's fused
dense+sparse path). ragline's sparse half of hybrid search comes from an
in-process BM25 index instead, so only dense embeddings are needed here.
The interface is kept so a local embedder (e.g. BGE-M3) can slot back in
during the on-prem phase without touching the pipeline.
"""

from abc import ABC, abstractmethod


class BaseEmbedder(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of chunk texts; returns one dense vector per text."""
        ...

    @abstractmethod
    async def embed_query(self, text: str, instruction: str | None = None) -> list[float]:
        """Embed a single query string; returns one dense vector.

        instruction: None = use the configured query instruction; "" = embed
        the raw text (for callers whose thresholds assume unprefixed queries).
        """
        ...
