"""ChatAgent — the 4-pass chat orchestrator with the memory on/off toggle.

Ported from raggles with the legacy (non-structured) pre-pass path, A/B
testing, and routing learner removed. The 4-pass design survives intact:

  Pass 1 (pre-pass, memory ON only): one structured LLM call that rewrites
          the query standalone and routes it (library/compound/retrieval).
  Pass 2 (answer): library summary, RAG, or both merged (compound).
  Pass 3 (post-pass, memory ON only): LLM rewrites summary/topics/key_facts.
  Pass 4 (confidence, memory ON only, flag-gated): intent-alignment score.

THE MEMORY TOGGLE (`use_memory`) gates the CURRENT turn only:
  * OFF: chat() skips the pre-pass (raw question, keyword-only routing, NO
    conversation context) and post_passes() skips passes 3+4. The latest
    query stands alone — no prior conversation reaches the prompt.
  * ON: the prompt is augmented with the ENTIRE prior conversation, INCLUDING
    turns taken while memory was off.
The turn is always appended to history and tagged memory_enabled=use_memory.
That flag is a record of the toggle state at this turn (it drives the UI frame
colour); it does NOT hide the turn from later memory-on prompts. Token totals
drop visibly when toggled off, which is the observable proof it works.

Pass 1+2 run in chat(); passes 3+4 run in post_passes() so the API can send
the answer to the client FIRST and finish memory/confidence work after.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import structlog

from ragline.agent.rag_agent import RAGAgent
from ragline.chat.intent_classifier import QueryIntent, create_intent_classifier
from ragline.chat.memory_store import MemoryStore
from ragline.chat.models import KeyFact, SessionMemory, TurnRecord
from ragline.chat.prepass_schema import PrePassResult
from ragline.chat.prompts import (
    CONFIDENCE_SYSTEM,
    FILE_LIST_PLACEHOLDER,
    LIBRARY_SYSTEM,
    LIBRARY_USER_TEMPLATE,
    POST_PASS_SYSTEM,
    STRUCTURED_PRE_PASS_SYSTEM,
    build_confidence_user,
    build_conversation_context,
    build_post_pass_user,
    build_structured_pre_pass_user,
)
from ragline.citations.formatter import format_for_api
from ragline.config import settings
from ragline.llm.base import BaseLLM
from ragline.storage.metadata_db import get_library_listing, get_library_summary, list_documents
from ragline.tracing.collector import TraceCollector, _current_trace, timed_step
from ragline.tracing.store import save_trace

log = structlog.get_logger()


def _complete_cut_off_marker(answer: str) -> str:
    """Finish a file-list marker the output ceiling cut off mid-way.

    An answer ending in "[[FILE_" would otherwise reach the user as a dangling
    fragment with no list. Only a trailing prefix of at least "[[" counts.
    """
    stripped = answer.rstrip()
    for n in range(len(FILE_LIST_PLACEHOLDER) - 1, 1, -1):
        if stripped.endswith(FILE_LIST_PLACEHOLDER[:n]):
            return stripped[:-n] + FILE_LIST_PLACEHOLDER
    return answer


def _splice_file_list(answer: str, listing: str) -> str:
    """Put `listing` where the first marker is, as its own block; drop repeats.

    The model is asked to write the marker on its own line but may put it
    mid-sentence; the list is markdown, so it must start and end on a line
    boundary either way.
    """
    head, _, tail = answer.partition(FILE_LIST_PLACEHOLDER)
    head = head.rstrip(" \t")
    if head and not head.endswith("\n"):
        head += "\n\n"
    tail = tail.replace(FILE_LIST_PLACEHOLDER, "").lstrip(" \t")
    if tail.strip() and not tail.startswith("\n"):
        tail = "\n\n" + tail
    return head + listing + tail


def scope_intersection(scope: list[str] | None, resolved: list[str] | None) -> list[str] | None:
    """Combine the user's retrieval scope with compound mode's resolved targets.

    None means "unrestricted" on either side. When both are set the result is
    their intersection — possibly EMPTY, which the pipeline treats as "search
    nothing": a user who scoped retrieval to folder A and asks about a manual
    in folder B gets no RAG hit rather than a silently widened search. Order
    follows `resolved` (the ranked match list) so the retry ladder is stable.
    """
    if scope is None:
        return resolved
    if resolved is None:
        return list(scope)
    wanted = set(scope)
    return [doc_id for doc_id in resolved if doc_id in wanted]


class ChatAgent:
    def __init__(self, rag_agent: RAGAgent, llm: BaseLLM, memory_store: MemoryStore):
        self._rag = rag_agent
        self._llm = llm
        self._memory = memory_store
        # Keyword classifier — covers routing when the pre-pass doesn't run
        # (memory off / structured pre-pass disabled).
        self._intent_classifier = create_intent_classifier(settings.intent_classifier)

    # ------------------------------------------------------------------
    # Passes 1 + 2
    # ------------------------------------------------------------------

    async def chat(
        self,
        session_id: str,
        question: str,
        use_memory: bool = True,
        store: MemoryStore | None = None,
        allowed_document_ids: list[str] | None = None,
    ) -> tuple[dict, SessionMemory, str]:
        """Run passes 1-2. Returns (formatted_response_dict, memory, rewritten_query).

        store: the per-user session store (auth). Defaults to the process-wide
        store for CLI/scripts and the AUTH_ENABLED=false dev mode.
        allowed_document_ids: the user's retrieval scope (Documents tab
        selection). None = whole corpus. It bounds EVERY RAG leg, including
        compound mode's own document resolution (intersected, never
        overridden) — the user's selection is a hard limit, not a hint.
        """
        memory = (store or self._memory).load(session_id)

        # One trace for the whole answer phase; the provider adds token usage
        # to it automatically on every LLM call.
        trace = TraceCollector(query=question, session_id=session_id)

        if use_memory and settings.use_structured_prepass:
            # --- Pass 1: structured pre-pass (single JSON LLM call) --------
            with timed_step("prepass"):
                prepass = await self._structured_pre_pass(memory, question)
            log.info(
                "structured pre-pass",
                original=question[:80],
                rewritten=prepass.rewritten_query[:80],
                mode=prepass.mode,
            )
            rewritten = prepass.rewritten_query
            # Memory context injected into the RAG prompt.
            conversation_context = build_conversation_context(
                memory, max_tokens=settings.memory_token_budget
            )
            # Map the pre-pass mode onto the pipeline switch below.
            library_mode = {"library": "pure", "compound": "compound"}.get(prepass.mode)
            excluded_source_files = prepass.excluded_sources
            retrieval_query = rewritten
        else:
            # --- Memory off (or structured pre-pass disabled): no pre-pass.
            # Raw question, no context; keyword routing keeps library mode
            # working ("how many documents?") at zero LLM cost.
            prepass = None
            rewritten = question
            conversation_context = ""
            intent, _confidence = await self._intent_classifier.classify(question)
            library_mode = {QueryIntent.LIBRARY: "pure", QueryIntent.COMPOUND: "compound"}.get(intent)
            excluded_source_files = []
            retrieval_query = question
            if not use_memory:
                log.info("memory disabled, skipping pre-pass", query=question[:80])

        # --- Pass 2: answer via the routed pipeline(s) ---------------------
        if library_mode == "pure":
            # Metadata-only answer; no vector retrieval at all.
            log.info("pure library query, skipping RAG", query=rewritten[:80])
            formatted = await self._library_query(rewritten)
            formatted["used_rag"] = False
            formatted["used_library"] = True
        elif library_mode == "compound":
            # Both pipelines: library overview + scoped RAG, then merge.
            log.info("compound library query, running both pipelines", query=rewritten[:80])
            library_result = await self._library_query(rewritten)
            # Try to pin retrieval to the documents the user referred to.
            resolved_ids = await self._resolve_allowed_document_ids(
                rewritten,
                original_query=question,
                excluded_source_files=excluded_source_files,
            )
            cited = await self._rag.query(
                retrieval_query,
                allowed_document_ids=scope_intersection(allowed_document_ids, resolved_ids),
                excluded_source_files=excluded_source_files,
                conversation_context=conversation_context,
            )
            formatted = format_for_api(cited)

            if formatted.get("sources"):
                # RAG found content — merge beneath the library overview.
                used_graph = formatted.get("used_graph", False)
                formatted = self._synthesize(rewritten, formatted, library_result)
                formatted["used_rag"] = True
                formatted["used_library"] = True
                formatted["used_graph"] = used_graph
            elif prepass and prepass.target_document_hints:
                # Empty retrieval: one retry using the pre-pass's document
                # hints to resolve an allow-list, then merge or concede.
                retry_doc_ids = await self._resolve_allowed_document_ids(
                    " ".join(prepass.target_document_hints),
                    original_query=question,
                    excluded_source_files=excluded_source_files,
                )
                retried = await self._rag.query(
                    retrieval_query,
                    allowed_document_ids=scope_intersection(allowed_document_ids, retry_doc_ids),
                    excluded_source_files=excluded_source_files,
                    conversation_context=conversation_context,
                )
                retried_formatted = format_for_api(retried)
                if retried_formatted.get("sources"):
                    used_graph = retried_formatted.get("used_graph", False)
                    formatted = self._synthesize(rewritten, retried_formatted, library_result)
                    formatted["used_rag"] = True
                    formatted["used_library"] = True
                    formatted["used_graph"] = used_graph
                else:
                    formatted = library_result
                    formatted["used_rag"] = False
                    formatted["used_library"] = True
            else:
                # No hints to retry with — the library overview stands alone.
                formatted = library_result
                formatted["used_rag"] = False
                formatted["used_library"] = True
        else:
            # Standard RAG.
            cited = await self._rag.query(
                retrieval_query,
                allowed_document_ids=allowed_document_ids,
                excluded_source_files=excluded_source_files,
                conversation_context=conversation_context,
            )
            formatted = format_for_api(cited)
            formatted["used_rag"] = True
            formatted["used_library"] = False

        # --- finalize + persist the answer-phase trace ---------------------
        trace_record = trace.finalize()
        log.info("query timing", total_ms=trace_record.total_ms, **trace.steps_rounded())
        try:
            await save_trace(trace_record)
        except Exception as e:
            log.warning("failed to save trace", error=str(e))

        # Whole-answer-phase token totals ride along with the response;
        # post_passes() adds its own tokens to these before the turn is saved.
        formatted["trace_id"] = trace_record.id
        formatted["prompt_tokens"] = trace_record.prompt_tokens
        formatted["completion_tokens"] = trace_record.completion_tokens

        return formatted, memory, rewritten

    # ------------------------------------------------------------------
    # Passes 3 + 4
    # ------------------------------------------------------------------

    async def post_passes(
        self,
        memory: SessionMemory,
        question: str,
        rewritten: str,
        formatted: dict,
        use_memory: bool = True,
        store: MemoryStore | None = None,
    ) -> tuple[SessionMemory, float | None, str | None]:
        """Run passes 3+4 in parallel. Returns (updated_memory, score, report)."""
        answer = formatted["answer"]

        # Defaults so a failure in passes 3-4 never prevents the turn from
        # being persisted below (an already-answered turn must not be lost to a
        # transient LLM/network error in the memory or confidence pass).
        updated_memory = memory
        score = None
        report = None

        if use_memory:
            # Fresh collector so post-pass token usage is captured and can be
            # merged into the response totals.
            post_trace = TraceCollector(query=question, session_id=memory.session_id)

            # Pure library-mode turns are deterministic metadata listings —
            # no retrieval, no sources for the evaluator to weigh, so the
            # intent-alignment rubric misreads them (it dings "unsupported by
            # sources"). Skip scoring; score stays None and the UI hides it.
            pure_library = bool(formatted.get("used_library")) and not formatted.get("used_rag")

            try:
                # Pass 3 (memory update) and pass 4 (confidence) run concurrently.
                # The two overlap, so their stage times can sum to more than
                # the post_passes wall time.
                with timed_step("post_passes"):
                    if settings.enable_confidence and not pure_library:
                        updated_memory, (score, report) = await asyncio.gather(
                            self._timed("memory_pass", self._post_pass(memory, question, answer)),
                            self._timed("confidence_pass",
                                        self._confidence_pass(memory, question, answer, rewritten)),
                        )
                    else:
                        updated_memory = await self._timed(
                            "memory_pass", self._post_pass(memory, question, answer)
                        )

                # Merge post-pass tokens into the whole-turn totals.
                formatted["prompt_tokens"] = (
                    (formatted.get("prompt_tokens") or 0) + post_trace.prompt_tokens
                )
                formatted["completion_tokens"] = (
                    (formatted.get("completion_tokens") or 0) + post_trace.completion_tokens
                )

                # Stamp the confidence score onto the persisted trace row.
                if score is not None and formatted.get("trace_id"):
                    try:
                        from sqlalchemy import select

                        from ragline.storage.metadata_db import _async_session
                        from ragline.tracing.models import QueryTrace

                        async with _async_session() as session:
                            result = await session.execute(
                                select(QueryTrace).where(QueryTrace.id == formatted["trace_id"])
                            )
                            trace_record = result.scalars().first()
                            if trace_record:
                                trace_record.confidence_score = score
                                session.add(trace_record)
                                await session.commit()
                    except Exception as e:
                        log.warning("failed to update trace confidence", error=str(e))
            except Exception as e:
                # Passes 3-4 failed (rate limit, network, etc.). Keep the
                # unchanged memory (no summary update) and fall through to STILL
                # persist the turn — the answer already reached the user.
                log.warning("post-passes failed; persisting turn without memory update", error=str(e))
                updated_memory = memory
                score = None
                report = None
            finally:
                # The post-pass collector is never persisted (the trace row
                # was saved with the answer), so its timings go to the log.
                log.info("post-pass timing", **post_trace.steps_rounded())
                # Deactivate the post-pass collector no matter what.
                _current_trace.set(None)
        else:
            # THE TOGGLE, other half: memory off skips passes 3+4 entirely.
            updated_memory = memory
            score = None
            report = None
            log.info("memory disabled, skipping post-passes")

        # The turn is ALWAYS recorded (history display needs it); the
        # memory_enabled flag just records the toggle state for this turn (UI
        # frame colour) — it does NOT gate the turn out of later memory-on
        # context, which sees the whole conversation.
        turn = TurnRecord(
            turn_number=updated_memory.turn_count + 1,
            user_query=question,
            rewritten_query=rewritten,
            answer=answer,
            spans=formatted["spans"],
            sources=formatted["sources"],
            model_used=formatted["model_used"],
            confidence_score=score,
            confidence_report=report,
            prompt_tokens=formatted.get("prompt_tokens") or None,
            completion_tokens=formatted.get("completion_tokens") or None,
            used_rag=bool(formatted.get("used_rag", True)),
            used_library=bool(formatted.get("used_library", False)),
            used_graph=bool(formatted.get("used_graph", False)),
            trace_id=formatted.get("trace_id"),
            memory_enabled=use_memory,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        updated_memory.turns.append(turn)

        # Persist the session (atomic write) into the caller's store.
        (store or self._memory).save(updated_memory)

        return updated_memory, score, report

    # ------------------------------------------------------------------
    # Compound-mode helpers
    # ------------------------------------------------------------------

    async def _resolve_allowed_document_ids(
        self,
        query: str,
        original_query: str = "",
        excluded_source_files: list[str] | None = None,
    ) -> list[str] | None:
        """Resolve likely target documents from library metadata.

        Used by compound mode so first-turn doc requests can retrieve in one
        response. Returns None when no clear match is found (falls back to
        unrestricted retrieval). Matching ladder, strongest first: direct
        mention -> quoted names -> ordinals -> single-doc ambiguity ->
        basename token overlap.
        """
        docs = [d for d in await list_documents() if d.status == "ready"]
        if not docs:
            return None

        # Honour exclusions before matching.
        excluded = {s.casefold() for s in (excluded_source_files or [])}
        docs = [
            d for d in docs
            if d.filename.casefold() not in excluded and Path(d.filename).name.casefold() not in excluded
        ]
        if not docs:
            return None

        q = f"{query} {original_query}".casefold()

        # 1) Direct string mention (full path or basename).
        direct = [
            d.id for d in docs
            if d.filename.casefold() in q or Path(d.filename).name.casefold() in q
        ]
        if direct:
            return list(dict.fromkeys(direct))

        # 2) Quoted filename-like references.
        quoted = [a or b for a, b in re.findall(r"'([^']+)'|\"([^\"]+)\"", query)]
        quoted = [x.strip().casefold() for x in quoted if x.strip()]
        quoted_hits = [
            d.id for d in docs
            if any(qv in d.filename.casefold() or qv in Path(d.filename).name.casefold() for qv in quoted)
        ]
        if quoted_hits:
            return list(dict.fromkeys(quoted_hits))

        # 2b) Ordinal references ("first doc", "second document", ...).
        docs_sorted = sorted(docs, key=lambda d: Path(d.filename).name.casefold())
        ordinal_markers = [
            ("first", 1), ("1st", 1), ("second", 2), ("2nd", 2),
            ("third", 3), ("3rd", 3), ("fourth", 4), ("4th", 4),
        ]
        for marker, idx in ordinal_markers:
            if marker in q and ("doc" in q or "document" in q or "manual" in q or "file" in q):
                if 1 <= idx <= len(docs_sorted):
                    return [docs_sorted[idx - 1].id]

        # 3) Ambiguous reference ("the doc") resolvable only when exactly one
        # document exists.
        ambiguous_ref = any(p in q for p in [
            "the doc", "the document", "this doc", "this document", "the manual", "this manual",
        ])
        if ambiguous_ref and len(docs) == 1:
            return [docs[0].id]

        # 4) Token overlap on basenames (>=4-char tokens).
        q_tokens = set(re.findall(r"[a-z0-9]{4,}", q))
        if not q_tokens:
            return None

        scored: list[tuple[int, str]] = []
        for d in docs:
            base_tokens = set(re.findall(r"[a-z0-9]{4,}", Path(d.filename).name.casefold()))
            score = len(q_tokens & base_tokens)
            if score > 0:
                scored.append((score, d.id))

        if not scored:
            return None

        best = max(scored, key=lambda t: t[0])[0]
        # Require at least two overlapping tokens for confidence.
        if best < 2:
            return None
        return [doc_id for score, doc_id in scored if score == best]

    @staticmethod
    async def _timed(name: str, awaitable):
        """Await `awaitable` as stage `name` (for passes run under gather)."""
        with timed_step(name):
            return await awaitable

    async def _library_query(self, question: str) -> dict:
        """Answer a library meta-question using the metadata DB (no retrieval)."""
        summary = await get_library_summary()
        messages = [
            {"role": "system", "content": LIBRARY_SYSTEM},
            {"role": "user", "content": LIBRARY_USER_TEMPLATE.format(
                query=question, library_summary=summary,
                file_list_placeholder=FILE_LIST_PLACEHOLDER,
            )},
        ]
        with timed_step("library_answer"):
            answer = await self._llm.complete(
                messages, temperature=0.0, max_tokens=settings.library_answer_max_tokens
            )
        answer = _complete_cut_off_marker(answer)
        if FILE_LIST_PLACEHOLDER in answer:
            # The list comes from the metadata DB, not the model: instant and exact.
            answer = _splice_file_list(answer, await get_library_listing())
        # Library answers have no chunk citations by design.
        return {
            "answer": answer,
            "spans": [],
            "sources": [],
            "query": question,
            "model_used": "",
        }

    @staticmethod
    def _synthesize(query: str, rag_result: dict, library_result: dict) -> dict:
        """Merge library context without rewriting cited RAG text.

        Deliberately mechanical (no LLM): keeping RAG spans untouched avoids
        citation/page drift from LLM rewrites. Library overview leads; the
        cited RAG answer follows with all spans/sources intact.
        """
        library_answer = (library_result.get("answer") or "").strip()
        rag_answer = (rag_result.get("answer") or "").strip()
        if not library_answer:
            return rag_result

        merged_answer = f"{library_answer}\n\n{rag_answer}" if rag_answer else library_answer

        # Library text becomes an uncited leading span.
        merged_spans = [
            {
                "text": library_answer + ("\n\n" if rag_result.get("spans") else ""),
                "citation_ids": [],
            }
        ]
        if rag_result.get("spans"):
            merged_spans.extend(rag_result["spans"])
        elif rag_answer:
            merged_spans.append({"text": rag_answer, "citation_ids": []})

        log.info(
            "compound merge complete",
            query=query[:80],
            rag_sources=len(rag_result.get("sources", [])),
        )
        return {
            "answer": merged_answer,
            "spans": merged_spans,
            "sources": rag_result["sources"],
            "query": rag_result.get("query", query),
            "model_used": rag_result.get("model_used", ""),
        }

    # ------------------------------------------------------------------
    # The individual LLM passes
    # ------------------------------------------------------------------

    async def _structured_pre_pass(self, memory: SessionMemory, question: str) -> PrePassResult:
        """Pass 1: one structured LLM call (rewrite + route + constraints)."""
        messages = [
            {"role": "system", "content": STRUCTURED_PRE_PASS_SYSTEM},
            {"role": "user", "content": build_structured_pre_pass_user(memory, question)},
        ]
        try:
            return await self._llm.complete_json(messages, PrePassResult)
        except Exception as e:
            # A failed pre-pass must never fail the turn: fall back to the
            # raw question routed as plain retrieval.
            log.warning("structured pre-pass failed, falling back", error=str(e))
            return PrePassResult(mode="retrieval", rewritten_query=question)

    async def _post_pass(self, memory: SessionMemory, question: str, answer: str) -> SessionMemory:
        """Pass 3: rewrite summary/topics/key_facts from the latest exchange."""
        messages = [
            {"role": "system", "content": POST_PASS_SYSTEM},
            {"role": "user", "content": build_post_pass_user(memory, question, answer)},
        ]
        raw = await self._llm.complete(messages, temperature=0.0)

        try:
            data = json.loads(raw)
            memory.summary = data.get("summary", memory.summary)
            memory.topics = data.get("topics", memory.topics)
            raw_facts = data.get("key_facts", [])
            memory.key_facts = [
                KeyFact(fact=f["fact"], source=f["source"], turn=memory.turn_count + 1)
                for f in raw_facts
                if isinstance(f, dict) and "fact" in f and "source" in f
            ]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            # Parse failure keeps the previous memory intact.
            log.warning("post-pass JSON parse failed", error=str(exc), raw=raw[:200])

        return memory

    async def _confidence_pass(
        self, memory: SessionMemory, question: str, answer: str, rewritten: str = ""
    ) -> tuple[float | None, str | None]:
        """Pass 4: score how well the answer matches the user's actual intent."""
        messages = [
            {"role": "system", "content": CONFIDENCE_SYSTEM},
            {"role": "user", "content": build_confidence_user(memory, question, answer, rewritten)},
        ]
        raw = await self._llm.complete(messages, temperature=0.0)

        try:
            data = json.loads(raw)
            score = float(data["score"])
            # Clamp defensive: models occasionally emit 1.2 or -0.1.
            score = max(0.0, min(1.0, score))
            report = data.get("report", "")
            return score, report
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            log.warning("confidence-pass JSON parse failed", error=str(exc), raw=raw[:200])
            return None, None
