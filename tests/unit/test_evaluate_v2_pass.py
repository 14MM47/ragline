"""scripts/evaluate.py v2 — one pass over a tiny golden set on a fake stack.

Exercises the wiring the pure-helper tests cannot: the per-question capture
hook on the pipeline, both answer paths (rag and chat with history seeding),
the per-question record shape, the error path, and the written results file.
The "stack" is three small fakes; metadata_db.get_document is patched out.
"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "evaluate.py"
spec = importlib.util.spec_from_file_location("evaluate_v2_pass", SCRIPT)
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def _hit(source: str, page: int, score: float = 0.9) -> SimpleNamespace:
    chunk = SimpleNamespace(source_file=f"hmi/x/{source}", page_start=page, page_end=page, chunk_id=f"{source}:{page}")
    return SimpleNamespace(chunk=chunk, score=score)


class FakePipeline:
    """Has the one attribute the harness touches: `capture`."""

    def __init__(self):
        self.capture = None

    def retrieved(self, merged, reranked):
        # What the real pipeline does at the end of retrieve().
        if self.capture is not None:
            self.capture(merged, reranked)


class FakeRagAgent:
    """RAGAgent stand-in: 'retrieves' through the fake pipeline, then answers."""

    def __init__(self, pipeline: FakePipeline, fail_on: str | None = None):
        self.pipeline = pipeline
        self.fail_on = fail_on

    async def query(self, question: str):
        if self.fail_on and self.fail_on in question:
            raise RuntimeError("endpoint down")
        self.pipeline.retrieved([_hit("a.pdf", 5), _hit("z.pdf", 1)], [_hit("a.pdf", 5)])
        if "unanswerable" in question:
            return SimpleNamespace(raw_text="I couldn't find any relevant information.", sources_used=[])
        citation = SimpleNamespace(source_file="hmi/x/a.pdf", page_number=5, document_id="doc-a")
        return SimpleNamespace(raw_text="It draws 11 W [1].", sources_used=[citation])


class FakeChatAgent:
    """ChatAgent stand-in: records the seeded memory it was handed."""

    def __init__(self, pipeline: FakePipeline):
        self.pipeline = pipeline
        self.seen_turns: dict[str, int] = {}

    async def chat(self, session_id, question, use_memory=True, store=None):
        memory = store.load(session_id)
        self.seen_turns[session_id] = memory.turn_count
        self.pipeline.retrieved([_hit("b.pdf", 2)], [_hit("b.pdf", 2)])
        formatted = {
            "answer": "The DA70A weighs 978 g [1].",
            "sources": [{"source_file": "hmi/x/b.pdf", "page_number": 2, "document_id": "doc-b"}],
            "prompt_tokens": 40, "completion_tokens": 12, "reasoning_chars": 7,
            "step_ms": {"answer": 500.0}, "used_rag": True, "used_library": False,
        }
        return formatted, memory, f"rewritten: {question}"


GOLDEN = [
    {"id": "A01", "category": "spec", "question": "What is the power?",
     "expected_sources": ["hmi/x/a.pdf"], "expected_pages": {"hmi/x/a.pdf": [5]}, "source_match": "any"},
    {"id": "E01", "category": "unanswerable", "question": "unanswerable thing?", "expected_sources": []},
    {"id": "F04", "category": "followup", "question": "And the DA70A?",
     "history": [{"user": "DA50A weight?", "assistant": "13 oz."}],
     "expected_sources": ["hmi/x/b.pdf"], "source_match": "any"},
    {"id": "X99", "category": "spec", "question": "please fail", "expected_sources": ["hmi/x/c.pdf"]},
]


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """Page sanity looks documents up; here there is no database."""
    import ragline.storage.metadata_db as db

    monkeypatch.setattr(db, "get_document", AsyncMock(return_value=None))


async def test_rag_pass_records_everything():
    """Hits, declines, retrieval metrics and the error path, all in one pass."""
    pipeline = FakePipeline()
    ctx = {"path": "rag", "pipeline": pipeline, "agent": FakeRagAgent(pipeline, fail_on="fail"), "run_id": "t"}
    results = await ev.run_pass(GOLDEN, ctx, repeat=1)
    by_id = {r["id"]: r for r in results}

    a = by_id["A01"]
    assert a["source_hit"] is True and a["cited"] and a["declined"] is False
    assert a["cited_pages"] == [("a.pdf", 5)]
    assert a["retrieval"]["calls"] == 1
    assert a["retrieval"]["recall_at_20"] == 1.0 and a["retrieval"]["page_hit"] is True
    assert [m["source"] for m in a["retrieval"]["merged"]] == ["a.pdf", "z.pdf"]
    assert a["history_replayed"] is False and a["think_residue"] is False

    e = by_id["E01"]
    assert e["source_hit"] is None and e["declined"] is True and e["retrieval"]["recall_at_8"] is None

    # The follow-up on the rag path is asked cold and flagged as such.
    assert by_id["F04"]["history_replayed"] is False

    x = by_id["X99"]
    assert x["error"] == "endpoint down" and x["source_hit"] is False and x["retrieval"]["calls"] == 0

    # The hook never stays attached between questions.
    assert pipeline.capture is None
    # Scored: A01 (hit), F04 (cold follow-up cites a.pdf, expects b.pdf: miss), X99 (error: miss).
    s = ev.summarise(results)
    assert s["hits"] == 1 and s["scored"] == 3 and s["errors"] == 1 and s["declined"] == 1


async def test_chat_pass_seeds_history(tmp_path):
    """The chat path seeds each session from the entry's history before asking."""
    from ragline.chat.memory_store import MemoryStore

    pipeline = FakePipeline()
    chat_agent = FakeChatAgent(pipeline)
    ctx = {"path": "chat", "pipeline": pipeline, "agent": None, "chat_agent": chat_agent,
           "store": MemoryStore(sessions_dir=tmp_path), "run_id": "t"}
    results = await ev.run_pass(GOLDEN[:3], ctx, repeat=1)
    by_id = {r["id"]: r for r in results}

    # F04 saw its one previous turn; A01 and E01 ran in empty sessions.
    assert chat_agent.seen_turns["eval-t-F04"] == 1
    assert chat_agent.seen_turns["eval-t-A01"] == 0
    f = by_id["F04"]
    assert f["history_replayed"] is True and f["source_hit"] is True
    assert f["rewritten_query"] == "rewritten: And the DA70A?"
    assert f["reasoning_chars"] == 7 and f["step_ms"] == {"answer": 500.0}
    assert f["used_rag"] is True and f["used_library"] is False


def test_results_file_shape(tmp_path):
    """What a written results file contains, from a summary and records."""
    results = [{"id": "A01", "source_hit": True, "cited": True, "pages_ok": True, "declined": False,
                "think_residue": False, "tokens": 10, "reasoning_chars": 0, "latency_s": 1.0, "step_ms": {},
                "retrieval": {"recall_at_20": 1.0, "recall_at_8": 1.0, "mrr": 1.0, "ndcg_at_8": 1.0,
                              "page_hit": None, "distractor_retrieved": None}, "distractor_cited": None}]
    doc = {"run": {"label": "t"}, **ev.summarise(results), "per_question": results}
    out = tmp_path / "r1.json"
    out.write_text(json.dumps(doc))
    loaded = json.loads(out.read_text())
    assert loaded["hit_rate"] == 1.0 and loaded["per_question"][0]["id"] == "A01"
    assert "retrieval_mean" in loaded and "think_residue" in loaded
