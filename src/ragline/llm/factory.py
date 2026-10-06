"""LLM factory — builds the process-wide provider instance.

Trivial by design: ragline has exactly one provider type (OpenAI-compatible).
The factory exists so call sites depend on get_llm() rather than a concrete
class, keeping the door open for alternatives without touching the pipeline.
"""

from functools import lru_cache

from ragline.config import settings
from ragline.llm.base import BaseLLM
from ragline.llm.openai_provider import OpenAIProvider


@lru_cache
def get_llm() -> BaseLLM:
    """Return the singleton LLM provider configured from settings."""
    # One provider for the whole process — the AsyncOpenAI client inside it
    # pools connections, so sharing is both safe and efficient.
    return OpenAIProvider(settings.llm_model)
