"""Chat route — the SSE endpoint plus session management.

Ported from raggles minus guardrails, legacy-session backfill, and per-stage
token fields. POST /chat streams two SSE frames:

  event: answer    — the cited answer (ChatResponse) as soon as passes 1-2
                     finish, so the user reads while passes 3-4 still run;
  event: complete  — confidence + whole-turn token totals (ConfidenceUpdate)
                     once the memory/confidence passes are done.

New in ragline: after passes 1-2, every cited source is enriched with its
document's original_path via ONE metadata-DB lookup — the provenance link
citations display. (original_path lives only in SQLite, never in Qdrant.)
"""

import asyncio
import time

import structlog
from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from ragline.api.dependencies import get_chat_agent, get_memory_store
from ragline.api.schemas import (
    ChatRequest,
    ChatResponse,
    CitationSchema,
    ConfidenceUpdate,
    SessionHistoryResponse,
    SessionSummarySchema,
    SpanSchema,
)
from ragline.auth.dependencies import AuthedUser, get_current_user
from ragline.chat.chat_agent import ChatAgent
from ragline.chat.memory_store import MemoryStore
from ragline.config import settings
from ragline.storage.metadata_db import get_documents_by_ids

log = structlog.get_logger()

router = APIRouter(tags=["chat"])


def _log_post_task_result(task: asyncio.Task) -> None:
    """Done-callback for the detached post-passes task.

    Retrieves the task's exception (so asyncio doesn't warn about an unretrieved
    exception when the client disconnected and nobody awaited it) and logs it.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.warning("post-passes failed (background)", error=str(exc))


async def enrich_sources_with_original_paths(
    sources: list[dict], user: AuthedUser | None = None
) -> None:
    """Fill each source's original_path and per-user `accessible` flag, in place.

    One bulk metadata query + one bulk ACL query for however many distinct
    documents the answer cited (typically <= 8). Missing documents or paths
    simply leave "".

    Access polarity: with auth on, `accessible` comes from the crawled NTFS
    ACL intersection (acl/access.py — the same function /content enforces
    with) and original_path is SUPPRESSED for inaccessible sources so the
    payload doesn't leak where a restricted file lives. With auth off (dev),
    everything is accessible, as before the ACL layer existed. The quoted
    snippets themselves stay visible either way — the documented product
    decision is "search everything, gate the source links".
    """
    doc_ids = list({s["document_id"] for s in sources if s.get("document_id")})
    if not doc_ids:
        return
    docs = await get_documents_by_ids(doc_ids)

    gate = settings.auth_enabled and user is not None
    acls: dict = {}
    groups: list[str] = []
    if gate:
        from ragline.acl.access import accessible as acl_accessible
        from ragline.auth.graph import effective_groups
        from ragline.storage.acl_models import get_acls_by_document_ids

        acls = await get_acls_by_document_ids(doc_ids)
        groups = await effective_groups(user)

    for source in sources:
        doc = docs.get(source.get("document_id", ""))
        path = doc.original_path if doc else ""
        if not gate:
            source["original_path"] = path
            source["accessible"] = True
            continue
        allowed = acl_accessible(user, acls.get(source.get("document_id", "")), groups=groups)
        source["accessible"] = allowed
        source["original_path"] = path if allowed else ""


@router.post("/chat")
async def chat(
    request: ChatRequest,
    agent: ChatAgent = Depends(get_chat_agent),
    store: MemoryStore = Depends(get_memory_store),
    user: AuthedUser = Depends(get_current_user),
):
    async def event_generator():
        start = time.perf_counter()
        use_memory = request.use_memory

        # --- Passes 1-2: pre-pass + answer --------------------------------
        formatted, memory, rewritten = await agent.chat(
            request.session_id,
            request.question,
            use_memory=use_memory,
            store=store,
            # Retrieval scope from the Documents tab selection; [] = no scope.
            allowed_document_ids=request.allowed_document_ids or None,
        )

        # NEW: attach original network paths + per-user access to the sources.
        try:
            await enrich_sources_with_original_paths(formatted["sources"], user=user)
        except Exception as e:
            # Provenance is best-effort — never block the answer on it.
            log.warning("original_path enrichment failed", error=str(e))

        elapsed_ms = (time.perf_counter() - start) * 1000

        # First SSE frame: the cited answer.
        chat_resp = ChatResponse(
            answer=formatted["answer"],
            spans=[SpanSchema(**s) for s in formatted["spans"]],
            sources=[CitationSchema(**s) for s in formatted["sources"]],
            query=formatted["query"],
            model_used=formatted["model_used"],
            session_id=request.session_id,
            rewritten_query=rewritten,
            turn_number=memory.turn_count + 1,
            used_rag=formatted.get("used_rag", True),
            used_library=formatted.get("used_library", False),
            used_graph=formatted.get("used_graph", False),
            response_time_ms=round(elapsed_ms, 1),
            memory_enabled=use_memory,
            trace_id=formatted.get("trace_id"),
        )
        # --- Passes 3-4: memory update + confidence ------------------------
        # post_passes is the ONLY place the turn is appended and saved. Launch
        # it as a DETACHED task BEFORE yielding the answer frame: a client
        # disconnect after the answer frame cancels this generator, and if the
        # task were created only after the yield it might never start (the
        # generator can be cancelled while suspended at the yield, before it is
        # resumed). ensure_future schedules it on the loop independently of this
        # generator's lifecycle, so the save always completes even if nobody is
        # listening for 'complete'. (post_passes reads formatted before it
        # mutates the token fields, and chat_resp already copied its values, so
        # running concurrently with the answer-frame send is safe.)
        post_task = asyncio.ensure_future(
            agent.post_passes(
                memory, request.question, rewritten, formatted, use_memory=use_memory, store=store
            )
        )
        # A detached task's exception must be retrieved or asyncio warns; log it
        # in case the client vanished before we await below.
        post_task.add_done_callback(_log_post_task_result)

        # First SSE frame: the cited answer.
        yield {"event": "answer", "data": chat_resp.model_dump_json()}

        # Await the already-running post-passes to emit the confidence frame.
        # shield keeps a cancellation here (client gone) from killing the task.
        # CancelledError (BaseException) is not caught by `except Exception`, so
        # it propagates and the detached task still finishes the save.
        try:
            _updated_memory, score, report = await asyncio.shield(post_task)
        except Exception as e:
            # Never break the SSE stream after the answer frame (rate limits
            # etc.) — the turn just completes without confidence.
            log.warning("post-passes failed", error=str(e))
            score = None
            report = None

        # Second SSE frame: confidence + whole-turn token totals.
        total_prompt = formatted.get("prompt_tokens", 0) or 0
        total_completion = formatted.get("completion_tokens", 0) or 0
        update = ConfidenceUpdate(
            confidence_score=score,
            confidence_report=report,
            prompt_tokens=total_prompt or None,
            completion_tokens=total_completion or None,
            total_tokens=(total_prompt + total_completion) or None,
            memory_enabled=use_memory,
        )
        yield {"event": "complete", "data": update.model_dump_json()}

    return EventSourceResponse(event_generator())


# --- Session management -----------------------------------------------------


@router.get("/sessions", response_model=list[SessionSummarySchema])
async def list_sessions(store: MemoryStore = Depends(get_memory_store)):
    """All sessions with turn counts and token totals (sidebar list)."""
    return store.list_sessions()


@router.get("/sessions/{session_id}", response_model=SessionHistoryResponse)
async def get_session(session_id: str, store: MemoryStore = Depends(get_memory_store)):
    """Full turn history for re-rendering a session in the UI."""
    memory = store.load(session_id)
    return SessionHistoryResponse(
        session_id=memory.session_id,
        created_at=memory.created_at,
        turns=[t.model_dump() for t in memory.turns],
    )


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, store: MemoryStore = Depends(get_memory_store)):
    """Delete a session and its memory file."""
    deleted = store.delete(session_id)
    return {"deleted": deleted}


@router.post("/sessions/{session_id}/compact")
async def compact_memory(
    session_id: str,
    agent: ChatAgent = Depends(get_chat_agent),
    store: MemoryStore = Depends(get_memory_store),
):
    """Aggressively compact memory: re-summarize and keep only the last 2 turns."""
    memory = store.load(session_id)
    if memory.turn_count == 0:
        return {"status": "ok", "turns_kept": 0}

    # Re-run the memory post-pass over the WHOLE conversation so the summary
    # captures everything before old turns are dropped.
    all_text = "\n".join(
        f"Q: {t.user_query}\nA: {t.answer[:200]}" for t in memory.turns
    )
    memory = await agent._post_pass(memory, "summarize all", all_text)

    # Keep only the last 2 turns; the summary now carries the rest.
    memory.turns = memory.turns[-2:]
    store.save(memory)

    return {"status": "ok", "turns_kept": len(memory.turns)}


@router.post("/sessions/{session_id}/clear-memory")
async def clear_memory(
    session_id: str,
    store: MemoryStore = Depends(get_memory_store),
):
    """Reset memory (summary/facts/topics/turns) but keep the session id."""
    memory = store.load(session_id)
    memory.summary = ""
    memory.key_facts = []
    memory.topics = []
    memory.turns = []
    store.save(memory)
    return {"status": "ok"}
