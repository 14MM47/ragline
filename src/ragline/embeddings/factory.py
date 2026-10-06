"""Embedder factory — builds the process-wide embedder instance.

Only the API embedder exists in v1. The factory indirection is kept so a
local model (e.g. BGE-M3 restoring raggles' dense+sparse named-vector path)
can be added in the on-prem phase behind the same get_embedder() call.
"""

from functools import lru_cache

from ragline.config import settings
from ragline.embeddings.base import BaseEmbedder
from ragline.embeddings.openai_embedder import OpenAIEmbedder


@lru_cache
def get_embedder() -> BaseEmbedder:
    """Return the singleton embedder configured from settings."""
    # Single embedder per process; its AsyncOpenAI client pools connections.
    return OpenAIEmbedder(settings.embedding_model)
