"""One-shot query route — RAG without sessions or memory.

Ported from raggles minus audit/retrieval-metrics. Primarily used by the
eval harness (scripts/evaluate.py); returns the cited answer plus whole-call
token totals, with sources enriched with original_path like chat.
"""

import time

import structlog
from fastapi import APIRouter, Depends

from ragline.agent.rag_agent import RAGAgent
from ragline.api.dependencies import get_rag_agent
from ragline.api.routes.chat import enrich_sources_with_original_paths
from ragline.api.schemas import CitationSchema, QueryRequest, QueryResponse, SpanSchema
from ragline.auth.dependencies import AuthedUser, get_current_user
from ragline.citations.formatter import format_for_api
from ragline.tracing.collector import TraceCollector
from ragline.tracing.store import save_trace

log = structlog.get_logger()

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    agent: RAGAgent = Depends(get_rag_agent),
    user: AuthedUser = Depends(get_current_user),
):
    """Answer one question with citations; no session, no memory passes."""
    start = time.perf_counter()
    # Collector captures token usage for the single RAG pass.
    trace = TraceCollector(query=request.question)
    # Retrieval scope from the Documents tab selection; [] means "no scope".
    cited = await agent.query(request.question, allowed_document_ids=request.allowed_document_ids or None)
    trace_record = trace.finalize()
    # Trace persistence is best-effort.
    try:
        await save_trace(trace_record)
    except Exception:
        pass

    formatted = format_for_api(cited)
    # Provenance + per-user access enrichment, same as chat.
    try:
        await enrich_sources_with_original_paths(formatted["sources"], user=user)
    except Exception as e:
        log.warning("original_path enrichment failed", error=str(e))

    elapsed_ms = (time.perf_counter() - start) * 1000
    return QueryResponse(
        answer=formatted["answer"],
        spans=[SpanSchema(**s) for s in formatted["spans"]],
        sources=[CitationSchema(**s) for s in formatted["sources"]],
        query=formatted["query"],
        model_used=formatted["model_used"],
        used_graph=formatted.get("used_graph", False),
        response_time_ms=round(elapsed_ms, 1),
        prompt_tokens=trace_record.prompt_tokens,
        completion_tokens=trace_record.completion_tokens,
    )
