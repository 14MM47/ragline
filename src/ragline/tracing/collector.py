"""TraceCollector — accumulates token usage and timing for one query.

Ported from raggles' collector but stripped from ~100 fields to the minimal
set. The mechanism is unchanged and load-bearing:

  * A ContextVar holds the "current" collector for the request. The LLM
    provider (llm/openai_provider.py) calls get_current_trace() after every
    completion and adds usage.prompt_tokens/completion_tokens to it.
  * Because EVERY LLM pass in a turn (pre-pass, answer, memory post-pass,
    confidence) goes through that one provider, whole-turn totals accumulate
    automatically with zero plumbing in the pipeline code.
  * Stage timings use the same ContextVar: pipeline code wraps a stage in
    `with timed_step("rerank"):` and the milliseconds land on whichever
    collector is current — or nowhere, outside a traced request.
"""

import json
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

from ragline.tracing.models import QueryTrace

# Holds the collector for the request currently being served. ContextVar is
# task-local under asyncio, so concurrent requests never share a collector.
_current_trace: ContextVar["TraceCollector | None"] = ContextVar("current_trace", default=None)


def get_current_trace() -> "TraceCollector | None":
    """Return the collector for the current request, or None outside one."""
    return _current_trace.get()


@contextmanager
def timed_step(name: str) -> Iterator[None]:
    """Time the wrapped block as stage `name` on the current collector.

    A no-op outside a traced request (scripts, tests). The collector is
    looked up on entry, so a block still records if the trace is finalized
    or swapped while it runs. Time is recorded even when the block raises.
    """
    trace = _current_trace.get()
    started = time.perf_counter()
    try:
        yield
    finally:
        if trace is not None:
            trace.add_step(name, (time.perf_counter() - started) * 1000)


class TraceCollector:
    """Accumulates trace data during a query and produces a QueryTrace row."""

    def __init__(self, query: str, session_id: str = ""):
        # Unique id for this trace; doubles as the API-visible trace_id.
        self.trace_id = str(uuid.uuid4())
        # Wall-clock start, for the total_ms figure computed in finalize().
        self.start_time = time.perf_counter()
        # The question as asked, and the owning chat session (if any).
        self.query = query
        self.session_id = session_id
        # Whole-turn token totals — incremented by the LLM provider after
        # every completion and every embedding-free LLM call in the turn.
        self.prompt_tokens = 0
        self.completion_tokens = 0
        # Response facts recorded by the chat route once the answer exists.
        self.citation_count = 0
        self.source_files: list[str] = []
        self.confidence_score: float | None = None
        # Stage name -> accumulated milliseconds (see timed_step). A stage
        # entered twice (e.g. two RAG legs in compound mode) sums.
        self.steps: dict[str, float] = {}
        # Register self as the active collector for this request context.
        self._token = _current_trace.set(self)

    def record_response(self, citation_count: int, source_files: list[str]) -> None:
        """Record answer-level facts (called by the chat route after citation extraction)."""
        self.citation_count = citation_count
        self.source_files = source_files

    def add_step(self, name: str, ms: float) -> None:
        """Add `ms` to stage `name`."""
        self.steps[name] = self.steps.get(name, 0.0) + ms

    def steps_rounded(self) -> dict[str, float]:
        """The stage timings, rounded to 0.1 ms, in first-entered order."""
        return {name: round(ms, 1) for name, ms in self.steps.items()}

    def finalize(self) -> QueryTrace:
        """Build the persistent QueryTrace row and deactivate this collector."""
        # Total wall time from construction to now, in milliseconds.
        total_ms = (time.perf_counter() - self.start_time) * 1000
        # Assemble the row from everything accumulated during the turn.
        trace = QueryTrace(
            id=self.trace_id,
            created_at=datetime.now(timezone.utc),
            query=self.query,
            session_id=self.session_id,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_ms=round(total_ms, 1),
            citation_count=self.citation_count,
            confidence_score=self.confidence_score,
            step_ms=json.dumps(self.steps_rounded()),
        )
        # Clear the ContextVar so stray later calls don't attribute tokens
        # to a finished trace.
        _current_trace.set(None)
        return trace
