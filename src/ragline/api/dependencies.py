"""Dependency wiring — lru_cache'd singletons injected into routes.

Ported from raggles, minus the runtime-flippable agent selection (ragline has
exactly one RAG agent, so everything can be cached). Each getter doubles as a
FastAPI dependency AND a plain factory for scripts/tests.
"""

import re
from functools import lru_cache
from pathlib import Path

from fastapi import Depends

from ragline.auth.dependencies import AuthedUser, get_current_user
from ragline.config import settings
from ragline.embeddings.base import BaseEmbedder
from ragline.embeddings.factory import get_embedder as _build_embedder
from ragline.llm.base import BaseLLM
from ragline.llm.factory import get_llm as _build_llm
from ragline.storage.file_store import BaseFileStore, create_file_store
from ragline.vectorstore.base import BaseVectorStore
from ragline.vectorstore.qdrant_store import QdrantVectorStore


@lru_cache
def get_vector_store() -> BaseVectorStore:
    """Singleton Qdrant store (one client per process)."""
    return QdrantVectorStore()


def get_embedder() -> BaseEmbedder:
    """Singleton embedder (factory itself is lru_cached)."""
    return _build_embedder()


def get_llm() -> BaseLLM:
    """Singleton LLM provider (factory itself is lru_cached)."""
    return _build_llm()


@lru_cache
def get_file_store() -> BaseFileStore:
    """Singleton local file store for uploaded documents."""
    return create_file_store()


@lru_cache
def get_retrieval_pipeline():
    """Singleton retrieval pipeline (holds the process-wide BM25 index).

    Imported lazily to keep module import order simple: pipeline pulls in
    the reranker, which loads sentence-transformers.
    """
    from ragline.retrieval.pipeline import RetrievalPipeline

    return RetrievalPipeline(
        vector_store=get_vector_store(),
        embedder=get_embedder(),
    )


@lru_cache
def get_rag_agent():
    """Singleton RAG agent (ragline has exactly one answer path)."""
    from ragline.agent.rag_agent import RAGAgent

    return RAGAgent(
        retrieval=get_retrieval_pipeline(),
        llm=get_llm(),
        embedder=get_embedder(),
    )


@lru_cache
def get_base_memory_store():
    """Process-wide unscoped store — CLI/scripts and the auth-off dev mode."""
    from ragline.chat.memory_store import MemoryStore

    return MemoryStore()


def get_memory_store(user: AuthedUser = Depends(get_current_user)):
    """Per-REQUEST session store, namespaced to the signed-in user.

    With auth on, each user's sessions live under memory_dir/<oid>/ — the
    session routes physically cannot see another user's files. With auth off
    (dev), this degrades to the historical unscoped store so existing local
    sessions stay visible.
    """
    if not settings.auth_enabled:
        return get_base_memory_store()
    from ragline.chat.memory_store import MemoryStore

    # oid is an Entra GUID; sanitize anyway — it becomes a directory name.
    safe_oid = re.sub(r"[^A-Za-z0-9-]", "_", user.oid) or "_invalid"
    return MemoryStore(sessions_dir=Path(settings.memory_dir) / safe_oid)


@lru_cache
def get_chat_agent():
    """Singleton chat agent orchestrating the 4-pass turn.

    Holds the UNSCOPED store as its default; authed routes pass their
    per-user store into chat()/post_passes() explicitly.
    """
    from ragline.chat.chat_agent import ChatAgent

    return ChatAgent(
        rag_agent=get_rag_agent(),
        llm=get_llm(),
        memory_store=get_base_memory_store(),
    )
