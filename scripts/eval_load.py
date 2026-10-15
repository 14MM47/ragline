"""eval_load.py — throughput probe: the stack under 1, 4 and 8 concurrent streams.

The golden-set run (evaluate.py) asks one question at a time, which measures
latency but not capacity. This probe asks a fixed subset of the golden
questions concurrently and records what a deployment decision needs:

  end-to-end (RAGAgent.query, the whole answer path) per concurrency level:
    * per-question latency: median / p90 / max
    * questions per minute over the level's wall time
    * answer tok/s = completion tokens / answer-stage seconds (prefill included)
    * errors (timeouts, 5xx, queue rejections — the sign that max_num_seqs is
      below the stream count)

  generation only (the LLM endpoint streamed the real answer prompt) per level:
    * TTFT: time to the first streamed token (prefill latency under load)
    * decode tok/s: streamed chunks after the first / time after the first
      (an approximation: one chunk ≈ one token on vLLM)

The prompt streamed in the second phase is built the way RAGAgent.query builds
it — retrieval, sandwich reorder, format_sources_prompt, QUERY_TEMPLATE under
SYSTEM_PROMPT — but WITHOUT graph or conversation context, so it is the
answer prompt's size class, not a byte-exact copy. Retrieval for it is done
sequentially before timing starts; only generation is measured.

The subset: `select_subset()` walks the categories round-robin, each ordered
by question number then vendor letter (A01, B01, C01, D01, A02, …) so vendors
are spread too, until it has 24 questions; follow-ups (chat-path only) and
library questions (not answerable via the rag path) are skipped. Deterministic
for a given golden set, so every rung and card probes the same questions.

Usage:
    python scripts/eval_load.py eval/golden_set_hmi.json -o eval/results/<run>/load.json \\
        --levels 1 4 8 --manifest-extra '{"gpu": "RTX PRO 6000"}'

The output carries the same run manifest as evaluate.py (reused from it).
Requires: Qdrant up, ingested corpus, configured .env, an LLM endpoint with
max_num_seqs >= the highest level (otherwise expect queueing or errors —
both are recorded, neither is hidden).
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# Allow running from the repo root without installing the package, and reuse
# the manifest/redaction helpers from evaluate.py (same directory).
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from ragline.logging_utils import configure_redaction, redact_text, redact_value  # noqa: E402

DEFAULT_SUBSET = 24
DEFAULT_LEVELS = (1, 4, 8)
# Categories the probe cannot ask on the one-shot path.
SKIP_CATEGORIES = {"followup", "library"}


# --------------------------------------------------------------------------
# Pure helpers (tests/unit/test_eval_load.py)
# --------------------------------------------------------------------------


def _id_order(item: dict) -> tuple:
    """Sort key: question number first, then the vendor-group letter."""
    qid = item.get("id") or ""
    digits = "".join(ch for ch in qid if ch.isdigit())
    return (int(digits) if digits else 0, qid)


def select_subset(golden: list[dict], n: int = DEFAULT_SUBSET) -> list[dict]:
    """A fixed, category- and vendor-balanced subset (see module docstring)."""
    by_cat: dict[str, list[dict]] = {}
    for item in sorted(golden, key=_id_order):
        cat = item.get("category") or "uncategorised"
        if cat in SKIP_CATEGORIES:
            continue
        by_cat.setdefault(cat, []).append(item)
    chosen: list[dict] = []
    cats = sorted(by_cat)
    while len(chosen) < n and any(by_cat[c] for c in cats):
        for cat in cats:                      # one from each category per round
            if by_cat[cat] and len(chosen) < n:
                chosen.append(by_cat[cat].pop(0))
    return chosen


def percentiles(values: list[float]) -> dict:
    """median / p90 / max of a list (None when empty), rounded for the report."""
    if not values:
        return {"median": None, "p90": None, "max": None}
    ordered = sorted(values)
    return {
        "median": round(statistics.median(ordered), 3),
        "p90": round(ordered[int(0.9 * (len(ordered) - 1))], 3),
        "max": round(ordered[-1], 3),
    }


async def run_concurrently(items: list, worker, concurrency: int) -> tuple[list, float]:
    """Run `worker(item)` over all items with at most `concurrency` in flight.

    Returns (results in item order, wall seconds). A worker's exception is
    captured in its slot as {"error": str} rather than cancelling the batch.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(item):
        async with semaphore:
            try:
                return await worker(item)
            except Exception as exc:  # noqa: BLE001 — one failure must not end the level
                return {"error": redact_text(str(exc))}

    started = time.perf_counter()
    results = await asyncio.gather(*(guarded(item) for item in items))
    return list(results), time.perf_counter() - started


def summarise_level(concurrency: int, rows: list[dict], wall_s: float) -> dict:
    """Aggregate one concurrency level's end-to-end rows."""
    ok = [r for r in rows if "error" not in r]
    latencies = [r["latency_s"] for r in ok]
    tok_s = [r["answer_tok_s"] for r in ok if r.get("answer_tok_s") is not None]
    return {
        "concurrency": concurrency,
        "questions": len(rows),
        "errors": len(rows) - len(ok),
        "wall_s": round(wall_s, 2),
        "questions_per_min": round(60 * len(ok) / wall_s, 2) if wall_s > 0 else None,
        "latency_s": percentiles(latencies),
        "answer_tok_s": percentiles(tok_s),
        "completion_tokens_total": sum(r.get("completion_tokens", 0) for r in ok),
    }


def summarise_stream_level(concurrency: int, rows: list[dict], wall_s: float) -> dict:
    """Aggregate one concurrency level's streaming (TTFT / decode) rows."""
    ok = [r for r in rows if "error" not in r]
    return {
        "concurrency": concurrency,
        "prompts": len(rows),
        "errors": len(rows) - len(ok),
        "wall_s": round(wall_s, 2),
        "ttft_s": percentiles([r["ttft_s"] for r in ok if r.get("ttft_s") is not None]),
        "decode_tok_s": percentiles([r["decode_tok_s"] for r in ok if r.get("decode_tok_s") is not None]),
        "chunks_total": sum(r.get("chunks", 0) for r in ok),
    }


async def stream_timing(stream_factory, messages: list[dict]) -> dict:
    """Time one streamed completion: TTFT, chunk count, decode rate."""
    started = time.perf_counter()
    first: float | None = None
    chunks = 0
    async for _delta in stream_factory(messages):
        chunks += 1
        if first is None:
            first = time.perf_counter()
    finished = time.perf_counter()
    if first is None:
        return {"ttft_s": None, "chunks": 0, "decode_tok_s": None, "total_s": round(finished - started, 3)}
    decode_s = finished - first
    return {
        "ttft_s": round(first - started, 3),
        "chunks": chunks,
        # Chunks after the first, over the time after the first.
        "decode_tok_s": round((chunks - 1) / decode_s, 2) if decode_s > 0 and chunks > 1 else None,
        "total_s": round(finished - started, 3),
    }


# --------------------------------------------------------------------------
# The two probes
# --------------------------------------------------------------------------


async def ask_end_to_end(agent, question: str) -> dict:
    """One RAGAgent.query() with its own trace; the row the level summary reads."""
    from ragline.tracing.collector import TraceCollector

    trace = TraceCollector(query=question)
    started = time.perf_counter()
    cited = await agent.query(question)
    latency = time.perf_counter() - started
    record = trace.finalize()
    steps = json.loads(record.step_ms)
    answer_s = steps.get("answer", 0.0) / 1000.0
    return {
        "latency_s": round(latency, 3),
        "completion_tokens": record.completion_tokens,
        "prompt_tokens": record.prompt_tokens,
        "answer_s": round(answer_s, 3),
        "answer_tok_s": round(record.completion_tokens / answer_s, 2) if answer_s > 0 else None,
        "cited": bool(cited.sources_used),
    }


async def build_answer_prompt(pipeline, question: str) -> list[dict]:
    """The answer prompt as RAGAgent.query builds it (no graph/conversation context)."""
    from ragline.agent.prompts import QUERY_TEMPLATE, SYSTEM_PROMPT
    from ragline.citations.prompt_based import format_sources_prompt
    from ragline.config import settings
    from ragline.retrieval.reorder import sandwich_reorder

    results = await pipeline.retrieve(question)
    if settings.enable_context_reordering:
        results = sandwich_reorder(results)
    chunks = [r.chunk for r in results]
    user_message = QUERY_TEMPLATE.format(query=question, sources=format_sources_prompt(chunks))
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_message}]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Throughput probe: the stack under concurrent load")
    parser.add_argument("golden_set", help="Path to the golden set JSON (the subset is drawn from it)")
    parser.add_argument("--output", "-o", help="Write the probe results to this JSON file")
    parser.add_argument("--levels", type=int, nargs="+", default=list(DEFAULT_LEVELS),
                        help="Concurrency levels to probe (default 1 4 8)")
    parser.add_argument("--subset", type=int, default=DEFAULT_SUBSET,
                        help=f"Questions in the fixed subset (default {DEFAULT_SUBSET})")
    parser.add_argument("--skip-stream", action="store_true",
                        help="Skip the TTFT/decode streaming phase (end-to-end only)")
    parser.add_argument("--label", default="", help="Free-text name for this stack/run")
    parser.add_argument("--thinking", choices=["off", "on", "unset"], default=None,
                        help="Override the thinking mode recorded (default: from LLM_EXTRA_BODY)")
    parser.add_argument("--campaign", default=None)
    parser.add_argument("--rung", default=None)
    parser.add_argument("--condition", default=None)
    parser.add_argument("--manifest-extra", default=None, help="JSON object (or @file) merged into the manifest")
    return parser


async def main() -> int:
    args = build_parser().parse_args()
    if any(level < 1 for level in args.levels):
        print("--levels must be >= 1", file=sys.stderr)
        return 1

    # Manifest helpers shared with evaluate.py (loaded as a sibling module).
    import evaluate as ev

    ev.parse_manifest_extra(args.manifest_extra)    # fail early on a bad value

    import logging

    from ragline.config import settings

    logging.basicConfig(level=settings.log_level.upper())
    configure_redaction()

    from ragline.api.dependencies import get_llm, get_rag_agent, get_retrieval_pipeline, get_vector_store
    from ragline.storage.metadata_db import init_db

    await init_db()
    pipeline = get_retrieval_pipeline()
    await pipeline.rebuild_bm25_index()
    index = {"collection": settings.qdrant_collection, "points": await get_vector_store().count()}

    golden = json.loads(Path(args.golden_set).read_text())
    subset = select_subset(golden, args.subset)
    print(f"Probe subset: {len(subset)} questions from {ev._public_path(args.golden_set)}; levels {args.levels}\n")

    # The manifest is evaluate.py's, with the probe's own arguments filled in.
    meta_args = SimpleNamespace(
        golden_set=args.golden_set, label=args.label, path="rag", thinking=args.thinking,
        repeats=1, warmup=0, seed=0, campaign=args.campaign, rung=args.rung,
        condition=args.condition, manifest_extra=args.manifest_extra,
    )
    run_meta = ev._run_metadata(meta_args, repeat=1, index=index)
    run_meta["probe"] = {"subset_ids": [q.get("id") for q in subset], "levels": args.levels}

    agent = get_rag_agent()
    llm = get_llm()

    # One untimed question so model, embedder and reranker are warm.
    try:
        await agent.query(subset[0]["question"])
    except Exception as exc:  # noqa: BLE001 — reported, not fatal
        print(redact_text(f"warm-up error: {exc}"))

    # --- phase 1: end-to-end under load ------------------------------------
    levels_out = []
    for level in args.levels:
        print(f"=== end-to-end, concurrency {level} ===")
        rows, wall = await run_concurrently(
            subset, lambda q: ask_end_to_end(agent, q["question"]), level
        )
        summary = summarise_level(level, rows, wall)
        summary["rows"] = [{"id": q.get("id"), **row} for q, row in zip(subset, rows)]
        levels_out.append(summary)
        print(f"  {summary['questions_per_min']} q/min  latency median {summary['latency_s']['median']} s  "
              f"p90 {summary['latency_s']['p90']} s  errors {summary['errors']}")

    # --- phase 2: generation only (TTFT / decode) under load ---------------
    stream_out = []
    if not args.skip_stream:
        print("\nBuilding answer prompts (retrieval, untimed)…")
        prompts = []
        for q in subset:
            try:
                prompts.append(await build_answer_prompt(pipeline, q["question"]))
            except Exception as exc:  # noqa: BLE001 — skip a prompt that cannot be built
                print(redact_text(f"  prompt build failed for {q.get('id')}: {exc}"))
        for level in args.levels:
            print(f"=== streaming, concurrency {level} ===")
            rows, wall = await run_concurrently(
                prompts, lambda messages: stream_timing(llm.stream, messages), level
            )
            summary = summarise_stream_level(level, rows, wall)
            summary["rows"] = rows
            stream_out.append(summary)
            print(f"  TTFT median {summary['ttft_s']['median']} s  p90 {summary['ttft_s']['p90']} s  "
                  f"decode median {summary['decode_tok_s']['median']} tok/s  errors {summary['errors']}")

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(redact_value({
            "run": run_meta,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "end_to_end": levels_out,
            "streaming": stream_out,
        }), indent=2))
        print(f"\nProbe results written to {ev._public_path(str(out))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
