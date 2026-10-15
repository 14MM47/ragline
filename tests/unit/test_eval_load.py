"""scripts/eval_load.py — the throughput probe's bookkeeping, on fakes.

Checks the fixed subset selection, that the concurrency limiter really caps
in-flight work (and uses the whole allowance), the per-level summaries, and
the streaming timer's TTFT / decode arithmetic. Fake agent and fake stream
with asyncio.sleep stand in for the stack; nothing is contacted.
"""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "eval_load.py"
spec = importlib.util.spec_from_file_location("eval_load_script", SCRIPT)
load = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load)


def _golden() -> list[dict]:
    """Four categories plus the two the probe must skip."""
    items = []
    for cat, n in (("spec", 10), ("comparison", 6), ("multihop", 3), ("unanswerable", 4),
                   ("followup", 5), ("library", 3)):
        items += [{"id": f"{cat[:1].upper()}{i:02d}", "category": cat, "question": f"{cat} {i}"} for i in range(n)]
    return items


def test_select_subset_is_balanced_and_deterministic():
    """Round-robin over categories by id; follow-ups and library skipped; stable."""
    golden = _golden()
    chosen = load.select_subset(golden, 8)
    assert [q["id"] for q in chosen] == ["C00", "M00", "S00", "U00", "C01", "M01", "S01", "U01"]
    assert all(q["category"] not in load.SKIP_CATEGORIES for q in load.select_subset(golden, 100))
    # Exhausting a category keeps drawing from the others.
    assert len(load.select_subset(golden, 23)) == 23
    assert load.select_subset(golden, 8) == chosen


def test_percentiles():
    """median / p90 / max; empty is None throughout."""
    assert load.percentiles([1.0, 2.0, 3.0, 4.0, 10.0]) == {"median": 3.0, "p90": 4.0, "max": 10.0}
    assert load.percentiles([]) == {"median": None, "p90": None, "max": None}


async def test_run_concurrently_caps_in_flight():
    """At most `concurrency` workers run at once, and that many actually do."""
    in_flight = 0
    peak = 0

    async def worker(item):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        if item == "boom":
            raise RuntimeError("endpoint down")
        return {"latency_s": 0.02, "completion_tokens": 10, "answer_tok_s": 500.0}

    items = ["a", "b", "boom", "d", "e", "f", "g", "h"]
    rows, wall = await load.run_concurrently(items, worker, 4)
    assert peak == 4                                     # used the whole allowance, never more
    assert len(rows) == 8 and rows[2] == {"error": "endpoint down"}
    assert 0.03 < wall < 0.5                             # two waves of ~20 ms, not eight
    summary = load.summarise_level(4, rows, wall)
    assert summary["questions"] == 8 and summary["errors"] == 1
    assert summary["completion_tokens_total"] == 70
    assert summary["latency_s"]["median"] == 0.02 and summary["answer_tok_s"]["max"] == 500.0
    assert summary["questions_per_min"] > 0


async def test_stream_timing_ttft_and_decode():
    """TTFT is the wait for the first chunk; decode rate counts the chunks after it."""
    async def fake_stream(messages):
        await asyncio.sleep(0.05)                        # prefill
        for _ in range(11):
            await asyncio.sleep(0.005)                   # ~200 tok/s
            yield "x"

    row = await load.stream_timing(fake_stream, [{"role": "user", "content": "q"}])
    assert row["chunks"] == 11
    assert 0.04 < row["ttft_s"] < 0.2
    assert 50 < row["decode_tok_s"] < 400                 # 10 chunks over ~50 ms, with timer slack

    async def empty_stream(messages):
        if False:
            yield ""

    assert (await load.stream_timing(empty_stream, []))["ttft_s"] is None
    s = load.summarise_stream_level(2, [row, {"error": "x"}], 0.5)
    assert s["prompts"] == 2 and s["errors"] == 1 and s["chunks_total"] == 11


async def test_ask_end_to_end_reads_the_trace(monkeypatch):
    """The end-to-end row takes tokens and the answer stage from the per-question trace."""
    from ragline.llm.openai_provider import _record_usage
    from ragline.tracing.collector import timed_step

    class Agent:
        async def query(self, question):
            with timed_step("answer"):
                await asyncio.sleep(0.01)
            _record_usage(SimpleNamespace(prompt_tokens=100, completion_tokens=20))
            return SimpleNamespace(sources_used=[object()])

    row = await load.ask_end_to_end(Agent(), "q")
    assert row["completion_tokens"] == 20 and row["prompt_tokens"] == 100 and row["cited"] is True
    assert row["answer_s"] >= 0.01 and row["answer_tok_s"] is not None and row["latency_s"] >= row["answer_s"]
