"""Chat data models — per-session memory persisted as one JSON file each.

Ported from raggles with the TurnRecord trimmed: the per-stage token fields
(prepass/rag/postpass/context) are gone — ragline reports one whole-turn
prompt+completion total per response.
"""

from pydantic import BaseModel


class KeyFact(BaseModel):
    """One remembered fact with its source document and the turn it arose in."""

    fact: str
    source: str
    turn: int


class TurnRecord(BaseModel):
    """Everything the UI needs to re-render one past exchange."""

    turn_number: int
    user_query: str
    # The pre-pass's standalone rewrite ("" or same as user_query when memory off).
    rewritten_query: str
    answer: str
    # Serialized spans/sources exactly as the API returned them (so history
    # re-renders citations without recomputation).
    spans: list[dict]
    sources: list[dict]
    model_used: str
    confidence_score: float | None = None
    confidence_report: str | None = None
    # Whole-turn token totals (all passes).
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    # Which pipeline(s) produced the answer.
    used_rag: bool = True
    used_library: bool = False
    used_graph: bool = False
    trace_id: str | None = None
    # Records the memory toggle state at THIS turn (drives the UI frame
    # colour). It gated whether this turn's OWN prompt got history; it does
    # NOT exclude the turn from later memory-on prompts, which see the whole
    # conversation regardless of any turn's memory state.
    memory_enabled: bool = True
    timestamp: str


class SessionMemory(BaseModel):
    """The full persisted state of one chat session."""

    session_id: str
    created_at: str
    # Rolling 1-2 sentence summary maintained by the post-pass.
    summary: str = ""
    # Topic tags maintained by the post-pass.
    topics: list[str] = []
    # Accumulated key facts (rewritten wholesale each post-pass).
    key_facts: list[KeyFact] = []
    # Full turn history (including memory-off turns, for display).
    turns: list[TurnRecord] = []

    @property
    def turn_count(self) -> int:
        return len(self.turns)
