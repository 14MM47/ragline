"""Retrieval scope — the Documents tab selection reaches every RAG leg.

ChatRequest/QueryRequest carry `allowed_document_ids`; ChatAgent.chat threads
it to RAGAgent.query in the standard branch and INTERSECTS it with compound
mode's own resolved targets (the selection is a hard limit, never widened).
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ragline.chat.chat_agent as chat_agent_module
from ragline.api.dependencies import get_rag_agent
from ragline.api.routes import query as query_route
from ragline.api.schemas import ChatRequest, QueryRequest
from ragline.auth.dependencies import AuthedUser, get_current_user
from ragline.chat.chat_agent import ChatAgent, scope_intersection
from ragline.chat.intent_classifier import QueryIntent
from ragline.chat.memory_store import MemoryStore
from ragline.config import settings

# --- helper ------------------------------------------------------------------


def test_scope_intersection_rules():
    assert scope_intersection(None, None) is None
    assert scope_intersection(None, ["a", "b"]) == ["a", "b"]
    assert scope_intersection(["a", "b"], None) == ["a", "b"]
    # Ranked order of the resolved list is kept; outsiders dropped.
    assert scope_intersection(["b", "a", "z"], ["c", "a", "b"]) == ["a", "b"]
    # Disjoint -> EMPTY list (search nothing), not None (search everything).
    assert scope_intersection(["a"], ["c"]) == []


# --- schemas -------------------------------------------------------------------


def test_document_id_length_cap():
    """Each id is bounded (uuid-sized); the list itself is not."""
    with pytest.raises(ValueError):
        QueryRequest(question="q", allowed_document_ids=["x" * 65])
    assert len(QueryRequest(question="q", allowed_document_ids=["d"] * 50_000).allowed_document_ids) == 50_000


def test_request_schemas_default_to_unscoped():
    assert QueryRequest(question="q").allowed_document_ids is None
    assert ChatRequest(session_id="s", question="q").allowed_document_ids is None
    assert ChatRequest(session_id="s", question="q", allowed_document_ids=["d1"]).allowed_document_ids == ["d1"]


# --- /query route --------------------------------------------------------------


class _RecordingRag:
    """Fake RAGAgent: records the kwargs of each query() call."""

    def __init__(self):
        self.calls = []

    async def query(self, question, allowed_document_ids=None, excluded_source_files=None, conversation_context=""):
        self.calls.append(
            {"question": question, "allowed": allowed_document_ids, "excluded": excluded_source_files}
        )
        # A minimal formatted-response-shaped dict; format_for_api is patched
        # to pass it through in the tests that use this fake.
        return {"answer": "a", "spans": [], "sources": [], "query": question, "model_used": "m"}


@pytest.fixture
def query_client(monkeypatch):
    rag = _RecordingRag()
    app = FastAPI()
    app.include_router(query_route.router, prefix="/api")
    app.dependency_overrides[get_rag_agent] = lambda: rag
    app.dependency_overrides[get_current_user] = lambda: AuthedUser(oid="u", upn="u@corp")
    monkeypatch.setattr(query_route, "format_for_api", lambda cited: dict(cited))

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(query_route, "save_trace", _noop)
    monkeypatch.setattr(query_route, "enrich_sources_with_original_paths", _noop)
    return TestClient(app), rag


def test_query_route_passes_scope(query_client):
    tc, rag = query_client
    assert tc.post("/api/query", json={"question": "q", "allowed_document_ids": ["d1", "d2"]}).status_code == 200
    assert rag.calls[-1]["allowed"] == ["d1", "d2"]
    # Omitted and [] both mean the whole corpus.
    tc.post("/api/query", json={"question": "q"})
    assert rag.calls[-1]["allowed"] is None
    tc.post("/api/query", json={"question": "q", "allowed_document_ids": []})
    assert rag.calls[-1]["allowed"] is None


# --- ChatAgent.chat ------------------------------------------------------------


@pytest.fixture
def chat_agent(tmp_path, monkeypatch):
    """ChatAgent with a recording RAG, no LLM calls (memory off => no pre-pass)."""
    rag = _RecordingRag()
    agent = ChatAgent(rag_agent=rag, llm=object(), memory_store=MemoryStore(tmp_path))
    monkeypatch.setattr(chat_agent_module, "format_for_api", lambda cited: dict(cited))

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(chat_agent_module, "save_trace", _noop)
    return agent, rag


async def test_chat_standard_branch_passes_scope(chat_agent, monkeypatch):
    agent, rag = chat_agent

    async def classify(question):
        return QueryIntent.RAG, 1.0

    monkeypatch.setattr(agent._intent_classifier, "classify", classify)
    await agent.chat("s1", "what is the IP rating?", use_memory=False, allowed_document_ids=["d1"])
    assert rag.calls[-1]["allowed"] == ["d1"]
    await agent.chat("s1", "what is the IP rating?", use_memory=False)
    assert rag.calls[-1]["allowed"] is None


async def test_chat_compound_branch_intersects_scope(chat_agent, monkeypatch):
    agent, rag = chat_agent

    async def classify(question):
        return QueryIntent.COMPOUND, 1.0

    async def library(query):
        return {"answer": "two manuals", "spans": [], "sources": []}

    async def resolve(query, original_query="", excluded_source_files=None):
        return ["d2", "d1", "d9"]

    monkeypatch.setattr(agent._intent_classifier, "classify", classify)
    monkeypatch.setattr(agent, "_library_query", library)
    monkeypatch.setattr(agent, "_resolve_allowed_document_ids", resolve)
    monkeypatch.setattr(settings, "use_structured_prepass", False)

    await agent.chat("s1", "compare the two manuals", use_memory=False, allowed_document_ids=["d1", "d3"])
    # Compound mode's ranked matches, cut down to the user's selection.
    assert rag.calls[-1]["allowed"] == ["d1"]

    await agent.chat("s1", "compare the two manuals", use_memory=False, allowed_document_ids=["d3"])
    # Disjoint: the RAG leg is told to search nothing rather than everything.
    assert rag.calls[-1]["allowed"] == []

    await agent.chat("s1", "compare the two manuals", use_memory=False)
    assert rag.calls[-1]["allowed"] == ["d2", "d1", "d9"]
