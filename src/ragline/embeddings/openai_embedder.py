"""OpenAIEmbedder — dense embeddings from an OpenAI-compatible endpoint.

Replaces raggles' LiteLLMEmbedder with the plain `openai` SDK. Uses the
embedding-specific endpoint config, which DEFAULTS to the LLM endpoint values
(one cloud endpoint serves both) but can point elsewhere for self-hosted
setups where the embedding model runs on its own vLLM instance/port.
"""

import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ragline.config import settings
from ragline.embeddings.base import BaseEmbedder

log = structlog.get_logger()

# Batch size per API request. TEI (the self-hosted embedder) enforces
# --max-client-batch-size=32 inputs AND a max-batch-tokens total, so the old
# value of 100 fails against it (a 34-input batch 422'd: "batch size 34 >
# maximum allowed batch size 32"). 16 stays under both the count cap and the
# token cap (16 x CHUNK_MAX_TOKENS=512 = 8192 tokens). OpenAI-cloud tolerates
# far larger batches, but 16 is safe everywhere.
_BATCH_SIZE = 16


class OpenAIEmbedder(BaseEmbedder):
    """BaseEmbedder implementation over the `openai` SDK embeddings API."""

    def __init__(self, model: str):
        # Embedding model name as the server knows it.
        self.model = model
        # Client aimed at the (possibly separate) embedding endpoint.
        # Placeholder key when none configured — same rationale as the LLM
        # provider: key-less local servers work, auth failures surface at
        # call time instead of import time.
        self._client = AsyncOpenAI(
            base_url=settings.effective_embedding_base_url,
            api_key=settings.effective_embedding_api_key or "not-needed",
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        """Embed one batch with retries; returns vectors in input order."""
        # Only pass `dimensions` when explicitly configured — most servers
        # reject the parameter or apply their model's native size anyway.
        kwargs: dict = {"model": self.model, "input": batch}
        if settings.embedding_dimensions:
            kwargs["dimensions"] = settings.embedding_dimensions
        # One embeddings API call for the whole batch.
        response = await self._client.embeddings.create(**kwargs)
        # The API may return items out of order — sort by index to be safe.
        items = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in items]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed any number of texts, batching requests of _BATCH_SIZE."""
        all_embeddings: list[list[float]] = []
        # Walk the input in fixed-size batches, preserving order.
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            all_embeddings.extend(await self._embed_batch(batch))
        log.debug("embedded texts", count=len(texts), model=self.model)
        return all_embeddings

    async def embed_query(self, text: str, instruction: str | None = None) -> list[float]:
        """Embed a single query — the batch path with one (maybe prefixed) element."""
        # None means "use the configured instruction"; "" forces a raw query.
        if instruction is None:
            instruction = settings.embedding_query_instruction
        # Qwen3-Embedding's query format — note NO space after "Query:". Source:
        # huggingface.co/Qwen/Qwen3-Embedding-8B model card, get_detailed_instruct():
        # f'Instruct: {task_description}\nQuery:{query}'.
        # Documents are embedded raw by embed(), so only this side changes.
        if instruction:
            text = f"Instruct: {instruction}\nQuery:{text}"
        result = await self.embed([text])
        return result[0]
