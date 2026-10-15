"""Stage 1 query-time fixes (docs/eval/ragline-fixes-plan.md items 2-6).

Result tidying, per-entity retrieval with reserved slots, neighbour expansion,
the question / search-query split and the answer-prompt rules.
"""

import pytest

from ragline.chat.prepass_schema import PrePassResult
from ragline.chunking.models import Chunk
from ragline.config import settings
from ragline.retrieval import pipeline as pl
from ragline.vectorstore.base import SearchResult


def _r(text: str, idx: int, doc: str = "d1", score: float = 1.0) -> SearchResult:
    """A search result over a minimal chunk; chunk_id encodes doc + index."""
    chunk = Chunk(text=text, source_file=f"{doc}.pdf", document_id=doc, page_start=1, page_end=1,
                  char_start=idx * 1000, char_end=idx * 1000 + len(text), chunk_index=idx,
                  chunk_id=f"{doc}-{idx}")
    return SearchResult(chunk=chunk, score=score)


# A body long enough to pass min_context_chars (100).
LONG = "The operating temperature range of this panel is 0 to 50 degrees C, non-condensing, per the spec table. "


# --- tidy_results --------------------------------------------------------------

def test_tidy_drops_duplicates_and_fragments_and_backfills_from_spares():
    """An exact-duplicate text and a footer fragment leave; the spares fill their places."""
    ranked = [_r(LONG + "a", 0), _r("  " + (LONG + "a").upper(), 1), _r("Page 4 | Doc 123", 2),
              _r(LONG + "b", 3), _r(LONG + "c", 4)]
    out = pl.tidy_results(ranked, 3)
    assert [r.chunk.chunk_index for r in out] == [0, 3, 4]


def test_tidy_brings_fragments_back_when_full_chunks_run_out():
    """Fewer full chunks than `keep`: fragments return (duplicates never), rank order kept."""
    ranked = [_r("short footer", 0), _r(LONG, 1), _r(LONG, 2), _r("another stub", 3)]
    out = pl.tidy_results(ranked, 3)
    assert [r.chunk.chunk_index for r in out] == [0, 1, 3]


def test_tidy_keeps_order_and_count_when_nothing_to_drop():
    """Clean input: the first `keep`, unchanged."""
    ranked = [_r(LONG + str(i), i) for i in range(6)]
    assert [r.chunk.chunk_index for r in pl.tidy_results(ranked, 4)] == [0, 1, 2, 3]


# --- merge_entity_results ------------------------------------------------------

def test_merge_reserves_slots_per_entity_then_fills_from_main():
    """Each product keeps its top `slots`; the main list fills the rest without repeats."""
    a = [_r(LONG, i, "A") for i in range(5)]
    b = [_r(LONG, i, "B") for i in range(5)]
    main = a[:6]  # the main query only finds product A
    out = pl.merge_entity_results(main, [a, b], keep=8, slots=2)
    keys = [(r.chunk.document_id, r.chunk.chunk_index) for r in out]
    assert keys[:4] == [("A", 0), ("A", 1), ("B", 0), ("B", 1)]
    # Main adds A2-A4 (5 A's in all); the last place comes from B's list.
    assert keys[4:] == [("A", 2), ("A", 3), ("A", 4), ("B", 2)]


def test_merge_shortfall_is_filled_round_robin_from_entities():
    """An empty main list: product lists are interleaved after the reserved slots."""
    a = [_r(LONG, i, "A") for i in range(4)]
    b = [_r(LONG, i, "B") for i in range(4)]
    out = pl.merge_entity_results([], [a, b], keep=6, slots=1)
    assert [(r.chunk.document_id, r.chunk.chunk_index) for r in out] == [
        ("A", 0), ("B", 0), ("A", 1), ("B", 1), ("A", 2), ("B", 2)]


# --- continues -----------------------------------------------------------------

@pytest.mark.parametrize("text,nxt,expected", [
    ("Specs\n| Model | Temp |\n| A | 50 C |", "Plain prose follows here.", True),   # ends on a table row
    ("Do this:\n1. Open the cover.", "Then more text.", True),                     # ends on a step
    ("Intro paragraph.", "| B | 55 C |\n| C | 60 C |", True),                      # next opens with a row
    ("Intro paragraph.", "Step 4 Close the cover.", True),                         # next opens with a step
    ("Prose ends here.", "New section prose.", False),
])
def test_continues(text, nxt, expected):
    """Table rows and numbered steps either side of the boundary mark a continuation."""
    assert pl.continues(text, nxt) is expected


# --- RetrievalPipeline: neighbours and multi-entity -----------------------------

class _Store:
    """Vector store double: only the neighbour lookup is used."""

    def __init__(self, chunks):
        self.chunks = {(c.document_id, c.chunk_index): c for c in chunks}
        self.asked = []

    async def get_chunks_by_position(self, wanted):
        self.asked.append(list(wanted))
        return [self.chunks[w] for w in wanted if w in self.chunks]


def _pipeline(monkeypatch, store=None):
    """A pipeline with no reranker model loaded."""
    monkeypatch.setattr(settings, "reranker_provider", "none")
    return pl.RetrievalPipeline(store or _Store([]), embedder=None)


async def test_expand_neighbours_inserts_continuation_after_parent(monkeypatch):
    """A hit ending on a table row gets its next chunk straight after it; prose hits do not."""
    table = _r("Specs\n| A | 50 C |", 3, score=0.9)
    prose = _r("Plain prose. " * 10, 7, score=0.5)
    store = _Store([_r("| B | 55 C |", 4).chunk, _r("More prose.", 8).chunk])
    p = _pipeline(monkeypatch, store)
    out = await p.expand_neighbours([table, prose])
    assert [r.chunk.chunk_index for r in out] == [3, 4, 7]
    assert out[1].score == 0.9


async def test_expand_neighbours_respects_cap_and_switch(monkeypatch):
    """At most neighbour_max_added are added; the switch turns it off."""
    hits = [_r(f"| row {i} |", i * 10) for i in range(3)]
    store = _Store([_r(f"| row {i}b |", i * 10 + 1).chunk for i in range(3)])
    p = _pipeline(monkeypatch, store)
    monkeypatch.setattr(settings, "neighbour_max_added", 2)
    assert len(await p.expand_neighbours(hits)) == 5
    monkeypatch.setattr(settings, "neighbour_expansion", False)
    assert len(await p.expand_neighbours(hits)) == 3


async def test_expand_neighbours_skips_chunks_already_present(monkeypatch):
    """A next chunk that is already in the results is not asked for or added twice."""
    hits = [_r("| a |", 1), _r("| b |", 2)]
    store = _Store([_r("| b |", 2).chunk, _r("| c |", 3).chunk])
    p = _pipeline(monkeypatch, store)
    out = await p.expand_neighbours(hits)
    assert [r.chunk.chunk_index for r in out] == [1, 2, 3]
    assert sorted(store.asked[0]) == [("d1", 0), ("d1", 3)]


async def test_expand_neighbours_adds_previous_chunk_before_a_mid_table_hit(monkeypatch):
    """A hit that opens with a table row gets the previous chunk (its header) placed before it."""
    hit = _r("| B | 55 C |\n| C | 60 C |", 5, score=0.7)
    store = _Store([_r("Operating temperature by model\n| Model | Temp |", 4).chunk])
    p = _pipeline(monkeypatch, store)
    out = await p.expand_neighbours([hit])
    assert [r.chunk.chunk_index for r in out] == [4, 5]
    assert out[0].score == 0.7


def test_merge_caps_the_main_fill_per_document():
    """The main list's fill takes at most doc_cap per document; the cap lifts only to fill a shortfall."""
    a = [_r(LONG, i, "A") for i in range(8)]
    b = [_r(LONG, i, "B") for i in range(1)]
    out = pl.merge_entity_results(a, [a, b], keep=6, slots=2, doc_cap=3)
    keys = [(r.chunk.document_id, r.chunk.chunk_index) for r in out]
    # Reserved: A0, A1, B0; main fill adds one more A (cap 3); then the cap lifts to fill.
    assert keys[:4] == [("A", 0), ("A", 1), ("B", 0), ("A", 2)]
    assert len(out) == 6


async def test_retrieve_multi_runs_each_query_and_captures_once(monkeypatch):
    """Main + per-product retrievals; one capture with the pooled candidates and the final list."""
    p = _pipeline(monkeypatch)
    monkeypatch.setattr(settings, "max_entity_queries", 2)
    seen = []

    async def fake(query, top_k, allowed, excluded):
        seen.append(query)
        doc = {"main": "A", "q1": "A", "q2": "B", "q3": "C"}[query]
        rs = [_r(LONG, i, doc) for i in range(8)]
        return rs, rs

    monkeypatch.setattr(p, "_retrieve", fake)
    captured = []
    p.capture = lambda merged, final: captured.append((merged, final))
    out = await p.retrieve_multi("main", ["q1", "q2", "q3"])
    assert sorted(seen) == ["main", "q1", "q2"]          # capped at max_entity_queries
    assert {r.chunk.document_id for r in out} == {"A", "B"}
    assert len(captured) == 1 and captured[0][1] == out
    assert len(captured[0][0]) == 16                       # A's pool (deduped) + B's pool


# --- RAGAgent: question vs search query -----------------------------------------

class _Retrieval:
    """Records which retrieval was used and with what query."""

    def __init__(self):
        self.calls = []

    async def retrieve(self, query, **kw):
        self.calls.append(("single", query))
        return [_r(LONG, 0)]

    async def retrieve_multi(self, query, entity_queries, **kw):
        self.calls.append(("multi", query, list(entity_queries)))
        return [_r(LONG, 0)]

    async def expand_neighbours(self, results):
        return results


class _LLM:
    model = "test"

    def __init__(self):
        self.messages = None

    async def complete(self, messages, **kw):
        self.messages = messages
        return "Answer [Source 1]"


async def test_answer_prompt_gets_the_question_and_retrieval_the_query(monkeypatch):
    """The keyword rewrite is searched; the user's question is what the model is asked."""
    from ragline.agent.rag_agent import RAGAgent

    monkeypatch.setattr(settings, "enable_knowledge_graph", False)
    retrieval, llm = _Retrieval(), _LLM()
    await RAGAgent(retrieval, llm).query("Which is hotter, X or Y?", retrieval_query="X Y max temp")
    assert retrieval.calls == [("single", "X Y max temp")]
    assert "Question: Which is hotter, X or Y?" in llm.messages[-1]["content"]


async def test_two_entity_queries_use_multi_retrieval(monkeypatch):
    """Two or more product queries switch to per-entity retrieval; one does not; 0 slots turns it off."""
    from ragline.agent.rag_agent import RAGAgent

    monkeypatch.setattr(settings, "enable_knowledge_graph", False)
    retrieval = _Retrieval()
    agent = RAGAgent(retrieval, _LLM())
    await agent.query("q", retrieval_query="k", entity_queries=["X temp", "Y temp"])
    await agent.query("q", retrieval_query="k", entity_queries=["X temp"])
    monkeypatch.setattr(settings, "entity_slots", 0)
    await agent.query("q", retrieval_query="k", entity_queries=["X temp", "Y temp"])
    assert [c[0] for c in retrieval.calls] == ["multi", "single", "single"]


# --- pre-pass schema and prompts -------------------------------------------------

def test_prepass_new_fields_default_for_old_replies():
    """A reply without the new fields still parses (answer = the typed question, no entities)."""
    res = PrePassResult.model_validate({"mode": "retrieval", "rewritten_query": "x"})
    assert res.answer_question == "" and res.entity_queries == []


def test_prompts_carry_the_new_rules():
    """The pre-pass asks for both new fields; the answer prompt carries rules 7-7d."""
    from ragline.agent.prompts import SYSTEM_PROMPT
    from ragline.chat.prompts import STRUCTURED_PRE_PASS_SYSTEM

    assert '"answer_question"' in STRUCTURED_PRE_PASS_SYSTEM and '"entity_queries"' in STRUCTURED_PRE_PASS_SYSTEM
    assert "Avoid repeating" not in SYSTEM_PROMPT
    for rule in ("7a.", "7b.", "7c.", "7d."):
        assert rule in SYSTEM_PROMPT


# --- code-review follow-ups ------------------------------------------------------

def test_tidy_keeps_short_table_rows_and_the_top_pick():
    """A short spec row, or a short top-ranked chunk, is never dropped as a fragment."""
    ranked = [_r("DOP-107WV 8.4 W", 0), _r("| DOP-107WV | 8.4 W |", 1), _r("Page 4", 2)] + \
        [_r(LONG + str(i), i) for i in range(3, 8)]
    out = pl.tidy_results(ranked, 4)
    assert [r.chunk.chunk_index for r in out] == [0, 1, 3, 4]


def test_lettered_prose_heading_is_not_a_step():
    """'A. Introduction' is a heading, not a lettered step; 'a) Remove…' and 'STEP 2' are steps."""
    assert pl.continues("Prose.", "A. Introduction to the panel") is False
    assert pl.continues("Prose.", "a) Remove the cover") is True
    assert pl.continues("Prose.", "STEP 2 Remove the cover") is True


async def test_expand_neighbours_ignores_chunks_without_a_document(monkeypatch):
    """A hit with no document_id is passed through and not looked up."""
    hit = _r("| a |", 1, doc="")
    store = _Store([])
    p = _pipeline(monkeypatch, store)
    assert [r.chunk.chunk_index for r in await p.expand_neighbours([hit])] == [1]
    assert store.asked == []


async def test_retrieve_multi_times_the_fan_out_once(monkeypatch):
    """Concurrent legs add no per-stage timings; the fan-out is one multi_retrieve step."""
    from ragline.tracing.collector import TraceCollector, timed_step

    p = _pipeline(monkeypatch)

    async def fake(query, top_k, allowed, excluded):
        with timed_step("rerank"):
            pass
        rs = [_r(LONG, i, query) for i in range(3)]
        return rs, rs

    monkeypatch.setattr(p, "_retrieve", fake)
    trace = TraceCollector(query="q")
    await p.retrieve_multi("m", ["x", "y"])
    steps = trace.steps_rounded()
    assert "multi_retrieve" in steps and "rerank" not in steps


async def test_multi_product_context_is_not_sandwich_reordered(monkeypatch):
    """The grouped multi-product order reaches the prompt as merged."""
    from ragline.agent.rag_agent import RAGAgent

    order = [_r(LONG + str(i), i, doc) for i, doc in enumerate("AABBCC")]

    class _Multi(_Retrieval):
        async def retrieve_multi(self, query, entity_queries, **kw):
            return list(order)

    seen = []

    async def keep(results):
        seen.extend(results)
        return results

    monkeypatch.setattr(settings, "enable_knowledge_graph", False)
    monkeypatch.setattr(settings, "enable_context_reordering", True)
    retrieval = _Multi()
    retrieval.expand_neighbours = keep
    await RAGAgent(retrieval, _LLM()).query("q", entity_queries=["A x", "B x"])
    assert [r.chunk.chunk_index for r in seen] == [0, 1, 2, 3, 4, 5]
