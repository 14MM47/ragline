"""eval_judge.py — grade evaluation answers with a frontier model, offline.

Runs AFTER evaluate.py, on its results files, with no GPU involved. For every
answer it asks the judge three structured questions (the prompts live in
eval/judge_prompts/ and are versioned; their hashes are recorded):

  correctness       correct / partial / wrong / abstained against the golden
                    entry's expected answer and evidence quotes. Unanswerable
                    entries are reported as declined / answered_wrong.
  faithfulness      the answer's factual claims, each supported or not by the
                    passages the system retrieved (fetched from Qdrant by
                    chunk id — the index must be the one the run used).
  citation_support  each citation used or not by the answer's content.

Transport: Claude Code headless on the existing login — no API key:

    claude -p --model <id> --output-format json --json-schema <schema>
           --tools "" --max-turns 1 --no-session-persistence

Answers are batched per call (defaults: 20 for correctness, 4 for
faithfulness, 10 for citation support — the passages make the latter two
heavier). Throttling or a failed call is retried with backoff. Output is
`<results>.judge.json` beside each results file; a re-run skips every task
whose prompt hash matches and whose ids are all graded (resumable), unless
--force.

Modes:
    python scripts/eval_judge.py eval/results/<campaign>/r2/off/r1.json
    python scripts/eval_judge.py <results…> --tasks correctness          # cheaper first pass
    python scripts/eval_judge.py <results> --calibrate eval/human_grades_2026-09-28.json
        grades correctness only and reports Cohen's kappa + the confusion
        matrix against the human grades; exit 1 below --kappa-min (0.8)
    python scripts/eval_judge.py <results> --second-opinion
        re-grades correctness for a stratified 20 % sample (plus every
        judge-vs-human disagreement when --calibrate is also given) through
        the Codex bridge (GPT-5.x) — each call is a billed OpenAI request —
        and reports judge agreement
    --dry-run builds every prompt and writes nothing; no model is called.

The judge sees the answer, the golden entry and the passages — never the
run's endpoint hosts or keys. Results files are already redacted.
"""

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROMPT_DIR = REPO / "eval" / "judge_prompts"
DEFAULT_GOLDEN = REPO / "eval" / "golden_set_hmi.json"
DEFAULT_MODEL = "claude-opus-5-5"
TASKS = ("correctness", "faithfulness", "citation_support")
DEFAULT_BATCH = {"correctness": 20, "faithfulness": 4, "citation_support": 10}
VERDICTS = ("correct", "partial", "wrong", "abstained")
# Backoff between attempts: throttling on the subscription is the usual cause.
BACKOFF_S = (5, 20, 60, 180, 600)
THROTTLE_MARKERS = ("rate limit", "usage limit", "overloaded", "too many requests", "429", "limit reached")

# JSON schemas handed to --json-schema; the judge's reply must validate.
SCHEMAS = {
    "correctness": {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "verdict": {"type": "string", "enum": list(VERDICTS)},
                "reason": {"type": "string"},
            },
            "required": ["id", "verdict", "reason"],
        }}},
        "required": ["items"],
    },
    "faithfulness": {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "claims": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "supported": {"type": "boolean"},
                        "passage": {"type": ["integer", "null"]},
                    },
                    "required": ["claim", "supported", "passage"],
                }},
            },
            "required": ["id", "claims"],
        }}},
        "required": ["items"],
    },
    "citation_support": {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "citations": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "page": {"type": ["integer", "null"]},
                        "used": {"type": "boolean"},
                    },
                    "required": ["source", "page", "used"],
                }},
            },
            "required": ["id", "citations"],
        }}},
        "required": ["items"],
    },
}


# --------------------------------------------------------------------------
# Prompts and batches (pure; tests/unit/test_eval_judge.py)
# --------------------------------------------------------------------------


def load_prompts(prompt_dir: Path = PROMPT_DIR) -> dict[str, tuple[str, str]]:
    """task -> (prompt text, sha256[:12]) for the three versioned prompts."""
    out = {}
    for task in TASKS:
        text = (prompt_dir / f"{task}.md").read_text(encoding="utf-8")
        out[task] = (text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12])
    return out


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def chunked(items: list, size: int) -> list[list]:
    """Split a list into consecutive batches of at most `size`."""
    return [items[i:i + size] for i in range(0, len(items), max(1, size))]


def correctness_items(records: list[dict], golden: dict[str, dict]) -> list[dict]:
    """What the correctness prompt shows per answer."""
    items = []
    for r in records:
        g = golden.get(r["id"], {})
        items.append({
            "id": r["id"],
            "category": r.get("category") or g.get("category"),
            "question": r["question"],
            "expected_answer": r.get("expected_answer") or g.get("expected_answer", ""),
            "evidence": [
                {"source": _basename(e["source"]), "page": e.get("page"), "quote": e.get("quote", "")}
                for e in g.get("evidence", [])
            ],
            "absence_check": g.get("absence_check"),
            "answer": r.get("answer", ""),
            "cited_sources": r.get("cited_sources", []),
        })
    return items


def faithfulness_items(records: list[dict], chunk_texts: dict[str, str]) -> list[dict]:
    """Answer plus the numbered retrieved passages (reranked top-8) it saw."""
    items = []
    for r in records:
        passages = []
        for n, c in enumerate(r.get("retrieval", {}).get("reranked", []), start=1):
            text = chunk_texts.get(c.get("chunk_id", ""))
            if text is not None:
                passages.append({"n": n, "source": c["source"],
                                 "pages": [c["page_start"], c["page_end"]], "text": text})
        items.append({"id": r["id"], "question": r["question"], "answer": r.get("answer", ""), "passages": passages})
    return items


def citation_items(records: list[dict], chunk_texts: dict[str, str]) -> list[dict]:
    """Answer plus each citation and the passage behind it (matched by file + page)."""
    items = []
    for r in records:
        citations = []
        for source, page in r.get("cited_pages", []):
            # The passage: the reranked chunk from that file covering that page.
            text = None
            for c in r.get("retrieval", {}).get("reranked", []):
                if c["source"] == source and page is not None and c["page_start"] <= page <= c["page_end"]:
                    text = chunk_texts.get(c.get("chunk_id", ""))
                    if text is not None:
                        break
            citations.append({"source": source, "page": page, "passage": text})
        if citations:
            items.append({"id": r["id"], "answer": r.get("answer", ""), "citations": citations})
    return items


def build_prompt(task: str, prompt_text: str, items: list[dict]) -> str:
    """The judge prompt: the task rubric followed by the items as a JSON block."""
    return (
        f"{prompt_text}\n\n"
        f"There are {len(items)} items. Return exactly one entry per item id.\n\n"
        "```json\n" + json.dumps(items, ensure_ascii=False, indent=1) + "\n```\n"
    )


def map_unanswerable(category: str | None, verdict: str) -> str:
    """Unanswerable entries report declined / answered_wrong instead of the 4 verdicts."""
    if category != "unanswerable":
        return verdict
    return "declined" if verdict == "abstained" else "answered_wrong"


# --------------------------------------------------------------------------
# Agreement statistics
# --------------------------------------------------------------------------


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    """Cohen's kappa between two label lists of equal length (None if empty)."""
    if not a or len(a) != len(b):
        return None
    n = len(a)
    labels = sorted(set(a) | set(b))
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum((ca[label] / n) * (cb[label] / n) for label in labels)
    if expected == 1.0:
        return 1.0
    return round((observed - expected) / (1 - expected), 4)


def confusion(a: list[str], b: list[str]) -> dict[str, dict[str, int]]:
    """Rows = first list's labels, columns = second list's labels."""
    labels = sorted(set(a) | set(b))
    table = {row: {col: 0 for col in labels} for row in labels}
    for x, y in zip(a, b):
        table[x][y] += 1
    return table


def stratified_sample(records: list[dict], fraction: float, seed: int = 0) -> list[str]:
    """A deterministic per-category sample of ids (at least one per category)."""
    rng = random.Random(seed)
    by_cat: dict[str, list[str]] = {}
    for r in records:
        by_cat.setdefault(r.get("category") or "uncategorised", []).append(r["id"])
    chosen: list[str] = []
    for cat in sorted(by_cat):
        ids = sorted(by_cat[cat])
        k = max(1, round(len(ids) * fraction))
        chosen += rng.sample(ids, min(k, len(ids)))
    return sorted(chosen)


# --------------------------------------------------------------------------
# Transports
# --------------------------------------------------------------------------


class JudgeError(RuntimeError):
    """A judge call failed after every retry."""


def call_claude(prompt: str, schema: dict, model: str, retries: int = len(BACKOFF_S) + 1,
                sleep=time.sleep) -> tuple[dict, dict]:
    """One headless Claude Code call; returns (structured output, call metadata).

    Retries on a non-zero exit, an error reply, or missing structured output,
    waiting BACKOFF_S between attempts (longer when the error text looks like
    throttling). The CLI's stdout is the only thing read; nothing is logged.
    """
    argv = [
        "claude", "-p", "--model", model, "--output-format", "json",
        "--json-schema", json.dumps(schema), "--tools", "", "--max-turns", "1",
        "--no-session-persistence",
    ]
    last_error = ""
    for attempt in range(retries):
        try:
            proc = subprocess.run(argv, input=prompt, capture_output=True, text=True, timeout=600, check=False)
            reply = json.loads(proc.stdout) if proc.stdout.strip() else {}
            output = reply.get("structured_output")
            if proc.returncode == 0 and not reply.get("is_error") and isinstance(output, dict):
                usage = reply.get("modelUsage") or {}
                return output, {
                    "model": next(iter(usage), model),      # the id the server reported
                    "cost_usd_reported": reply.get("total_cost_usd"),
                    "duration_ms": reply.get("duration_ms"),
                    "attempts": attempt + 1,
                }
            last_error = (reply.get("result") or proc.stderr or f"exit {proc.returncode}")[:300]
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"[:300]
        if attempt < retries - 1:
            wait = BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)]
            if any(marker in last_error.lower() for marker in THROTTLE_MARKERS):
                wait = max(wait, 180)
            print(f"    judge call failed ({last_error[:80]}); retry in {wait}s", file=sys.stderr)
            sleep(wait)
    raise JudgeError(last_error)


def call_codex(prompt: str, state_base: Path, bridge: Path | None = None) -> dict:
    """One Codex bridge call (billed); the reply must be JSON (fences tolerated)."""
    bridge = bridge or Path.home() / ".claude" / "scripts" / "codex_bridge.sh"
    env = dict(os.environ)
    env.setdefault("CODEX_BRIDGE_TIMEOUT", "900")
    proc = subprocess.run([str(bridge), "start", "--state", str(state_base), "-"], input=prompt,
                          capture_output=True, text=True, timeout=1000, check=False, env=env)
    if proc.returncode != 0:
        raise JudgeError(f"codex bridge exit {proc.returncode}: {proc.stderr[:200]}")
    text = proc.stdout.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return json.loads(text)


# --------------------------------------------------------------------------
# Judge file handling
# --------------------------------------------------------------------------


def judge_path(results_path: Path) -> Path:
    """<results>.judge.json beside the results file."""
    return results_path.with_name(results_path.stem + ".judge.json")


def load_judge(path: Path) -> dict:
    """The existing judge document, or an empty one."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"tasks": {}, "per_question": {}}


def pending_ids(doc: dict, task: str, prompt_hash: str, ids: list[str]) -> list[str]:
    """The ids this task still has to grade with this prompt.

    Everything when the task was never run or ran with another prompt; otherwise
    the ids with no entry and the ids whose entry is an error (e.g. the judge
    returned no verdict for them) — an error is not a grade, so a re-run retries it.
    """
    meta = doc["tasks"].get(task)
    if not meta or meta.get("prompt_hash") != prompt_hash:
        return list(ids)
    entries = doc["per_question"]
    return [qid for qid in ids
            if task not in entries.get(qid, {}) or "error" in entries[qid][task]]


def task_done(doc: dict, task: str, prompt_hash: str, ids: list[str]) -> bool:
    """True when this task was graded with this prompt for every id (errors don't count)."""
    return not pending_ids(doc, task, prompt_hash, ids)


def merge_task(doc: dict, task: str, results: list[dict], meta: dict, accumulate: bool = False) -> None:
    """Write a task's per-item results and metadata into the judge document.

    accumulate=True (a resume that re-graded only some ids) adds this run's calls
    and reported cost to the task's earlier totals instead of replacing them.
    """
    for item in results:
        doc["per_question"].setdefault(item["id"], {})[task] = {k: v for k, v in item.items() if k != "id"}
    old = doc["tasks"].get(task) or {}
    if accumulate and old:
        meta = {**meta, "calls": old.get("calls", 0) + meta["calls"],
                "cost_usd_reported": round(old.get("cost_usd_reported", 0.0) + meta["cost_usd_reported"], 4)}
    doc["tasks"][task] = meta


def summarise_judge(doc: dict, records: list[dict]) -> dict:
    """Headline counts from the judge document."""
    cats = {r["id"]: r.get("category") for r in records}
    verdicts = Counter()
    by_cat: dict[str, Counter] = {}
    claims_total = claims_supported = citations_total = citations_used = 0
    for qid, entry in doc["per_question"].items():
        c = entry.get("correctness")
        if c:
            label = c.get("label") or c.get("verdict")
            verdicts[label] += 1
            by_cat.setdefault(cats.get(qid) or "uncategorised", Counter())[label] += 1
        for claim in (entry.get("faithfulness") or {}).get("claims", []):
            claims_total += 1
            claims_supported += 1 if claim.get("supported") else 0
        for cit in (entry.get("citation_support") or {}).get("citations", []):
            citations_total += 1
            citations_used += 1 if cit.get("used") else 0
    answerable = [qid for qid, cat in cats.items() if cat != "unanswerable"]
    correct = sum(1 for qid in answerable
                  if (doc["per_question"].get(qid, {}).get("correctness") or {}).get("label") == "correct")
    return {
        "verdicts": dict(verdicts),
        "by_category": {cat: dict(counter) for cat, counter in sorted(by_cat.items())},
        "correct_rate_answerable": round(correct / len(answerable), 4) if answerable else None,
        "claims": {"total": claims_total, "supported": claims_supported,
                   "supported_rate": round(claims_supported / claims_total, 4) if claims_total else None},
        "citations": {"total": citations_total, "used": citations_used,
                      "used_rate": round(citations_used / citations_total, 4) if citations_total else None},
    }


# --------------------------------------------------------------------------
# Running the tasks
# --------------------------------------------------------------------------


async def fetch_chunk_texts(chunk_ids: list[str]) -> dict[str, str]:
    """chunk id -> text from the vector store (the run's frozen index)."""
    from ragline.api.dependencies import get_vector_store

    texts: dict[str, str] = {}
    ids = sorted({c for c in chunk_ids if c})
    for batch in chunked(ids, 200):
        for chunk in await get_vector_store().get_chunks_by_ids(batch):
            texts[chunk.chunk_id] = chunk.text
    return texts


def run_task(task: str, items: list[dict], prompt: tuple[str, str], model: str, batch: int,
             caller, dry_run: bool) -> tuple[list[dict], dict]:
    """Grade `items` in batches; returns (per-item results, task metadata)."""
    results: list[dict] = []
    calls = 0
    cost = 0.0
    model_seen = model
    for group in chunked(items, batch):
        text = build_prompt(task, prompt[0], group)
        if dry_run:
            print(f"    [dry-run] {task}: batch of {len(group)} ({len(text)} chars)")
            continue
        output, meta = caller(text, SCHEMAS[task], model)
        calls += 1
        cost += meta.get("cost_usd_reported") or 0.0
        model_seen = meta.get("model") or model_seen
        got = {entry["id"]: entry for entry in output.get("items", [])}
        for item in group:
            entry = got.get(item["id"])
            if entry is None:
                # The judge skipped an id: record that, never invent a verdict.
                entry = {"id": item["id"], "error": "no verdict returned"}
            results.append(entry)
        print(f"    {task}: {len(results)}/{len(items)} graded ({calls} calls)")
    meta = {
        "prompt_hash": prompt[1], "model": model_seen, "calls": calls,
        "cost_usd_reported": round(cost, 4), "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return results, meta


def grade_file(results_path: Path, golden: dict[str, dict], prompts: dict, args, caller) -> dict:
    """Judge one results file for the requested tasks; returns the judge doc."""
    data = json.loads(results_path.read_text(encoding="utf-8"))
    records = [r for r in data["per_question"] if r.get("answer") or r.get("error") is None]
    jpath = judge_path(results_path)
    doc = load_judge(jpath)
    doc["results_file"] = str(results_path)
    doc["golden_sha256"] = data.get("run", {}).get("golden_sha256")
    print(f"== {results_path} ({len(records)} answers)")

    for task in args.tasks:
        # Build the task's items for every answer first: a task applies only to the
        # answers it has items for (citation support skips answers that cite
        # nothing), and only those can be pending.
        if task == "correctness":
            all_items = correctness_items(records, golden)
        else:
            has_capture = any(r.get("retrieval", {}).get("reranked") for r in records)
            if not has_capture or args.chunks == "none":
                print(f"    {task}: skipped (no retrieval capture in this file or --chunks none)")
                continue
            import asyncio

            chunk_ids = [c.get("chunk_id", "") for r in records for c in r["retrieval"]["reranked"]]
            texts = asyncio.run(fetch_chunk_texts(chunk_ids))
            all_items = (faithfulness_items(records, texts) if task == "faithfulness"
                         else citation_items(records, texts))
        item_ids = [item["id"] for item in all_items]
        # Which of those still need grading: all with --force, else the missing and errored ones.
        todo = set(item_ids) if args.force else set(pending_ids(doc, task, prompts[task][1], item_ids))
        if not todo:
            print(f"    {task}: already graded with prompt {prompts[task][1]}, skipping")
            continue
        partial = len(todo) < len(item_ids)
        if partial:
            print(f"    {task}: re-grading {len(todo)} missing or errored answer(s): {sorted(todo)}")
        items = [item for item in all_items if item["id"] in todo]
        results, meta = run_task(task, items, prompts[task], args.model, args.batch[task], caller, args.dry_run)
        if args.dry_run:
            continue
        if task == "correctness":
            cats = {r["id"]: r.get("category") for r in records}
            for entry in results:
                if "verdict" in entry:
                    entry["label"] = map_unanswerable(cats.get(entry["id"]), entry["verdict"])
        merge_task(doc, task, results, meta, accumulate=partial)
        doc["summary"] = summarise_judge(doc, records)
        jpath.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"    wrote {jpath}")
    return doc


def calibrate(doc: dict, grades_path: Path) -> tuple[float | None, dict, list[str]]:
    """Kappa and confusion between the judge's verdicts and the human grades."""
    grades = {g["id"]: g["label"] for g in json.loads(grades_path.read_text(encoding="utf-8"))["grades"]}
    judge: list[str] = []
    human: list[str] = []
    disagreements: list[str] = []
    for qid, label in sorted(grades.items()):
        verdict = (doc["per_question"].get(qid, {}).get("correctness") or {}).get("verdict")
        if verdict is None:
            continue
        judge.append(verdict)
        human.append(label)
        if verdict != label:
            disagreements.append(qid)
    return cohen_kappa(human, judge), confusion(human, judge), disagreements


def second_opinion(doc: dict, records: list[dict], golden: dict, prompts: dict, args,
                   extra_ids: list[str], codex=call_codex) -> dict:
    """Re-grade correctness for a stratified sample (+extra ids) through Codex."""
    sample = sorted(set(stratified_sample(records, args.sample)) | set(extra_ids))
    by_id = {r["id"]: r for r in records}
    items = correctness_items([by_id[q] for q in sample if q in by_id], golden)
    state = Path(args.codex_state or (Path.home() / ".cache" / "ragline-judge2"))
    state.parent.mkdir(parents=True, exist_ok=True)
    calls = 0
    for group in chunked(items, args.batch["correctness"]):
        prompt = build_prompt("correctness", prompts["correctness"][0], group)
        if args.dry_run:
            print(f"    [dry-run] second opinion: batch of {len(group)}")
            continue
        output = codex(prompt, state)
        calls += 1
        for entry in output.get("items", []):
            doc["per_question"].setdefault(entry["id"], {})["correctness_judge2"] = {
                k: v for k, v in entry.items() if k != "id"}
    first = [doc["per_question"][q]["correctness"]["verdict"] for q in sample
             if "correctness" in doc["per_question"].get(q, {}) and "correctness_judge2" in doc["per_question"][q]]
    second = [doc["per_question"][q]["correctness_judge2"]["verdict"] for q in sample
              if "correctness" in doc["per_question"].get(q, {}) and "correctness_judge2" in doc["per_question"][q]]
    doc["second_opinion"] = {
        "sample_ids": sample, "codex_calls": calls, "prompt_hash": prompts["correctness"][1],
        "kappa_vs_judge": cohen_kappa(first, second), "confusion": confusion(first, second),
    }
    print(f"    second opinion: {calls} Codex call(s) (billed), "
          f"kappa vs judge {doc['second_opinion']['kappa_vs_judge']}")
    return doc["second_opinion"]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Grade evaluation answers with a frontier judge (offline)")
    parser.add_argument("results", nargs="+", help="evaluate.py results file(s)")
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN), help="Golden set the runs used")
    parser.add_argument("--tasks", nargs="+", choices=TASKS, default=list(TASKS))
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Judge model id passed to claude --model")
    parser.add_argument("--batch-correctness", type=int, default=DEFAULT_BATCH["correctness"])
    parser.add_argument("--batch-faithfulness", type=int, default=DEFAULT_BATCH["faithfulness"])
    parser.add_argument("--batch-citation", type=int, default=DEFAULT_BATCH["citation_support"])
    parser.add_argument("--chunks", choices=["qdrant", "none"], default="qdrant",
                        help="Where passages come from for faithfulness/citation (none = skip those tasks)")
    parser.add_argument("--force", action="store_true", help="Re-grade even when already graded")
    parser.add_argument("--dry-run", action="store_true", help="Build prompts, call nothing, write nothing")
    parser.add_argument("--calibrate", default=None, help="Human grades JSON: report kappa and the confusion matrix")
    parser.add_argument("--kappa-min", type=float, default=0.8, help="Exit 1 when calibration kappa is below this")
    parser.add_argument("--second-opinion", action="store_true", help="Codex re-grade of a sample (billed)")
    parser.add_argument("--sample", type=float, default=0.2, help="Second-opinion sample fraction per category")
    parser.add_argument("--codex-state", default=None, help="State path prefix for the Codex bridge")
    parser.add_argument("--prompt-dir", default=str(PROMPT_DIR))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.batch = {"correctness": args.batch_correctness, "faithfulness": args.batch_faithfulness,
                  "citation_support": args.batch_citation}
    if args.calibrate:
        args.tasks = ["correctness"]                  # calibration is a correctness measurement
    if not args.dry_run and shutil.which("claude") is None:
        print("claude CLI not found on PATH", file=sys.stderr)
        return 1
    golden = {g["id"]: g for g in json.loads(Path(args.golden).read_text(encoding="utf-8"))}
    prompts = load_prompts(Path(args.prompt_dir))
    print("judge prompts: " + ", ".join(f"{t} {h}" for t, (_text, h) in prompts.items()))

    exit_code = 0
    for results_file in args.results:
        path = Path(results_file)
        doc = grade_file(path, golden, prompts, args, call_claude)
        data = json.loads(path.read_text(encoding="utf-8"))
        records = [r for r in data["per_question"] if r.get("answer") or r.get("error") is None]
        disagreements: list[str] = []
        if args.calibrate and not args.dry_run:
            kappa, table, disagreements = calibrate(doc, Path(args.calibrate))
            doc["calibration"] = {"human_grades": args.calibrate, "kappa": kappa, "confusion": table,
                                  "disagreements": disagreements, "kappa_min": args.kappa_min}
            graded = sum(sum(r.values()) for r in table.values())
            print(f"\n    calibration: kappa {kappa} over {graded} graded answers")
            print("    confusion (rows human, cols judge):")
            labels = sorted(table)
            print("      " + " ".join(f"{label:>9}" for label in labels))
            for row in labels:
                print(f"      {row:>9} " + " ".join(f"{table[row][col]:>9}" for col in labels))
            if disagreements:
                print(f"    disagreements: {', '.join(disagreements)}")
            if kappa is None or kappa < args.kappa_min:
                print(f"    FAILED: kappa below {args.kappa_min}")
                exit_code = 1
        if args.second_opinion:
            second_opinion(doc, records, golden, prompts, args, disagreements)
        if not args.dry_run:
            judge_path(path).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            summary = doc.get("summary", {})
            print(f"    verdicts: {summary.get('verdicts')}  correct rate (answerable): "
                  f"{summary.get('correct_rate_answerable')}\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
