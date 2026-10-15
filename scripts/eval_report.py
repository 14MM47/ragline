"""eval_report.py — aggregate a campaign's runs into report.json, figures and REPORT.md.

Reads everything evaluate.py, eval_load.py, eval_judge.py and eval_campaign.py
left under eval/results/<campaign>/:

    <rung>/<condition>/r<N>.json         per-question records + manifest
    <rung>/<condition>/r<N>.judge.json   judge labels (correctness, faithfulness, citations)
    <rung>/<condition>/load.json         throughput probe
    spend.jsonl                          pod sessions and their cost

and produces, in the campaign directory (or --out-dir):

    report.json          every number in the report, machine-readable
    figures/*.svg        correctness by rung with CIs, category heatmap,
                         thinking ON−OFF deltas, latency vs correctness,
                         cost per 1,000 questions, retrieval by category,
                         and cost vs throughput per card when several cards ran
    REPORT.md            the tables and figures, ready for the narrative

Statistics (docs/evaluation-plan.md §5):
  * correctness = judge label `correct` on answerable questions; each
    question's score is its mean over repeats, the configuration's rate is
    the mean over questions, and the 95 % CI is a 10,000-sample bootstrap over
    questions (seeded, so the report is reproducible)
  * comparisons are paired by question id: the CI of the mean difference
    comes from the same bootstrap, and McNemar's exact test is applied to
    majority-vote correctness per question (b = only A right, c = only B right)
  * cost per 1,000 questions = rate × sequential wall time / questions, and
    the same at the probe's best questions-per-minute when a probe ran

A configuration is one (rung, condition) — or (rung, condition, GPU) when
the same model ran on several cards (Phase 3). The baseline for pairwise
tables is `--baseline` (default r2/off, the recorded 27B stack).

Usage:
    python scripts/eval_report.py eval/results/eval-2026-10
    python scripts/eval_report.py eval/results/eval-2026-10 --baseline r2/off --no-figures

matplotlib is imported only when figures are drawn; without it the report
is still written and the figure section says why they are missing.
"""

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BOOTSTRAP_SAMPLES = 10_000
SEED = 20261013
RUNG_ORDER = ["r1", "r1b", "r2", "r3", "r4", "r5", "r6"]      # size order for the figures


# --------------------------------------------------------------------------
# Statistics (pure; tests/unit/test_eval_report.py)
# --------------------------------------------------------------------------


def bootstrap_ci(values: list[float], samples: int = BOOTSTRAP_SAMPLES, seed: int = SEED) -> tuple[float, float, float]:
    """(mean, lower, upper): percentile bootstrap of the mean over the items."""
    if not values:
        return float("nan"), float("nan"), float("nan")
    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(samples, len(arr)))
    means = arr[idx].mean(axis=1)
    return float(arr.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def paired_bootstrap(a: list[float], b: list[float], samples: int = BOOTSTRAP_SAMPLES,
                     seed: int = SEED) -> tuple[float, float, float]:
    """(mean difference a−b, lower, upper) over paired items."""
    if not a or len(a) != len(b):
        return float("nan"), float("nan"), float("nan")
    diff = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    return bootstrap_ci(diff.tolist(), samples, seed)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value for the discordant counts b and c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def majority(values: list[float]) -> bool:
    """Majority vote over repeats (ties count as not correct)."""
    return sum(values) > len(values) / 2


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def thinking_of(meta: dict) -> str | None:
    """Thinking mode of a run, robust to manifests recorded before 2026-10-15.

    ON became answer-only on 2026-10-14 (ANSWER_EXTRA_BODY); the harness then
    still labelled such runs from LLM_EXTRA_BODY alone, i.e. "off". The answer
    body decides: the manifest field when present, else the condition env.
    """
    body = meta.get("answer_extra_body")
    if body is None:
        raw = ((meta.get("extra") or {}).get("condition_env") or {}).get("ANSWER_EXTRA_BODY") or ""
        try:
            body = json.loads(raw.strip("'")) if raw.strip("'") else {}
        except json.JSONDecodeError:
            body = {}
    flag = ((body or {}).get("chat_template_kwargs") or {}).get("enable_thinking")
    if flag is True:
        return "on"
    if flag is False:
        return "off"
    return meta.get("thinking")

def load_campaign_dir(root: Path) -> dict:
    """Collect runs by configuration; returns {"configs": {...}, "ledger": [...]}."""
    configs: dict[str, dict] = {}
    for run_file in sorted(root.glob("*/*/r*.json")):
        if run_file.name.endswith(".judge.json"):
            continue
        run = json.loads(run_file.read_text(encoding="utf-8"))
        meta = run.get("run", {})
        rung = meta.get("rung") or run_file.parts[-3]
        cond = meta.get("condition") or run_file.parts[-2]
        gpu = (meta.get("extra") or {}).get("gpu")
        key = f"{rung}/{cond}" + (f"@{gpu}" if _multi_gpu(root, rung, cond) else "")
        cfg = configs.setdefault(key, {
            "rung": rung, "condition": cond, "gpu": gpu, "model": (meta.get("extra") or {}).get("model_id")
            or meta.get("llm_model"), "thinking": thinking_of(meta), "path": meta.get("path"),
            "rate_usd_per_hr": (meta.get("extra") or {}).get("rate_usd_per_hr"),
            "quantization": (meta.get("extra") or {}).get("quantization"),
            # Pod boot time, POD UP to ready, from the campaign runner (None for runs before it was recorded).
            "boot_s": (meta.get("extra") or {}).get("boot_s"),
            "runs": [], "judges": [], "load": None, "manifest": meta,
        })
        cfg["runs"].append(run)
        judge_file = run_file.with_name(run_file.stem + ".judge.json")
        cfg["judges"].append(json.loads(judge_file.read_text(encoding="utf-8")) if judge_file.exists() else None)
        load_file = run_file.with_name("load.json")
        if load_file.exists() and cfg["load"] is None:
            cfg["load"] = json.loads(load_file.read_text(encoding="utf-8"))
    ledger = []
    ledger_file = root / "spend.jsonl"
    if ledger_file.exists():
        ledger = [json.loads(line) for line in ledger_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {"configs": configs, "ledger": ledger}


def _multi_gpu(root: Path, rung: str, cond: str) -> bool:
    """True when the same rung/condition has runs from more than one GPU."""
    gpus = set()
    for run_file in (root / rung / cond).glob("r*.json"):
        if run_file.name.endswith(".judge.json"):
            continue
        meta = json.loads(run_file.read_text(encoding="utf-8")).get("run", {})
        gpus.add((meta.get("extra") or {}).get("gpu"))
    return len(gpus) > 1


# --------------------------------------------------------------------------
# Per-configuration metrics
# --------------------------------------------------------------------------


def question_scores(cfg: dict) -> dict[str, list[float]]:
    """id -> correctness indicators over repeats (answerable questions only, judged)."""
    scores: dict[str, list[float]] = defaultdict(list)
    for run, judge in zip(cfg["runs"], cfg["judges"]):
        if judge is None:
            continue
        labels = judge.get("per_question", {})
        for rec in run["per_question"]:
            if rec.get("category") == "unanswerable":
                continue
            entry = (labels.get(rec["id"]) or {}).get("correctness")
            if entry and "label" in entry:
                scores[rec["id"]].append(1.0 if entry["label"] == "correct" else 0.0)
    return dict(scores)


def summarise_config(cfg: dict) -> dict:
    """All headline numbers for one configuration."""
    runs = cfg["runs"]
    records = [r for run in runs for r in run["per_question"]]
    scores = question_scores(cfg)
    per_q = [statistics.mean(v) for v in scores.values()]
    mean, lo, hi = bootstrap_ci(per_q) if per_q else (float("nan"),) * 3

    # Category breakdown (judged, answerable) and unanswerable behaviour.
    by_cat: dict[str, list[float]] = defaultdict(list)
    cats = {r["id"]: r.get("category") for r in records}
    for qid, vals in scores.items():
        by_cat[cats.get(qid) or "uncategorised"].append(statistics.mean(vals))
    declined = answered_wrong = unans = 0
    claims_total = claims_ok = cits_total = cits_used = 0
    partial = wrong = abstained = 0
    for judge in cfg["judges"]:
        if judge is None:
            continue
        for qid, entry in judge.get("per_question", {}).items():
            c = entry.get("correctness") or {}
            label = c.get("label")
            if cats.get(qid) == "unanswerable":
                unans += 1
                declined += label == "declined"
                answered_wrong += label == "answered_wrong"
            else:
                partial += label == "partial"
                wrong += label == "wrong"
                abstained += label == "abstained"
            for claim in (entry.get("faithfulness") or {}).get("claims", []):
                claims_total += 1
                claims_ok += bool(claim.get("supported"))
            for cit in (entry.get("citation_support") or {}).get("citations", []):
                cits_total += 1
                cits_used += bool(cit.get("used"))

    latencies = [r["latency_s"] for r in records if r.get("latency_s") is not None]
    latencies.sort()
    calls_view = call_metrics(records)
    tokens = [r.get("tokens", 0) for r in records]
    reasoning = [r.get("reasoning_chars", 0) for r in records]
    retr_keys = ("recall_at_20", "recall_at_8", "mrr", "ndcg_at_8", "page_hit")
    retrieval = {k: _mean([r.get("retrieval", {}).get(k) for r in records]) for k in retr_keys}
    retr_by_cat: dict[str, list[float]] = defaultdict(list)
    for r in records:
        v = r.get("retrieval", {}).get("recall_at_8")
        if v is not None:
            retr_by_cat[r.get("category") or "uncategorised"].append(v)

    n_questions = len(runs[0]["per_question"]) if runs else 0
    wall_h = sum(latencies) / 3600 if latencies else 0.0
    rate = cfg.get("rate_usd_per_hr")
    cost_seq = (rate * wall_h / len(latencies) * 1000) if rate and latencies else None
    load = cfg.get("load") or {}
    best_qpm = max((lvl.get("questions_per_min") or 0) for lvl in load.get("end_to_end", [])) if load else None
    cost_conc = (rate / (best_qpm * 60) * 1000) if rate and best_qpm else None
    ttft = decode = None
    if load.get("streaming"):
        first = load["streaming"][0]
        ttft, decode = first.get("ttft_s", {}).get("median"), first.get("decode_tok_s", {}).get("median")

    return {
        "key": f"{cfg['rung']}/{cfg['condition']}" + (f"@{cfg['gpu']}" if "@" in cfg.get("key", "") else ""),
        "rung": cfg["rung"], "condition": cfg["condition"], "gpu": cfg["gpu"], "model": cfg["model"],
        "thinking": cfg["thinking"], "path": cfg["path"], "quantization": cfg["quantization"],
        "repeats": len(runs), "questions": n_questions, "judged_questions": len(scores),
        "correct_rate": _r(mean), "correct_ci": [_r(lo), _r(hi)],
        "partial": partial, "wrong": wrong, "abstained": abstained,
        "unanswerable": {"n": unans, "declined": declined, "answered_wrong": answered_wrong,
                         "declined_rate": _r(declined / unans) if unans else None},
        "by_category": {cat: _r(statistics.mean(v)) for cat, v in sorted(by_cat.items())},
        "faithfulness": {"claims": claims_total,
                         "supported_rate": _r(claims_ok / claims_total) if claims_total else None},
        "citations": {"n": cits_total, "used_rate": _r(cits_used / cits_total) if cits_total else None},
        "source_hit_rate": _mean([run.get("hit_rate") for run in runs]),
        "retrieval": retrieval,
        "retrieval_recall_at_8_by_category": {cat: _r(statistics.mean(v)) for cat, v in sorted(retr_by_cat.items())},
        "declined_answers": sum(1 for r in records if r.get("declined")),
        "think_residue": sum(1 for r in records if r.get("think_residue")),
        "errors": sum(1 for r in records if r.get("error")),
        "latency_median_s": _r(statistics.median(latencies)) if latencies else None,
        "latency_p90_s": _r(latencies[int(0.9 * (len(latencies) - 1))]) if latencies else None,
        "tokens_per_question": _r(statistics.mean(tokens)) if tokens else None,
        "reasoning_chars_per_question": _r(statistics.mean(reasoning)) if reasoning else None,
        "calls": calls_view,
        "ttft_median_s": ttft, "decode_tok_s_median": decode,
        "questions_per_min": {str(lvl.get("concurrency")): lvl.get("questions_per_min")
                              for lvl in load.get("end_to_end", [])},
        "rate_usd_per_hr": rate,
        "boot_s": cfg.get("boot_s"),
        "cost_per_1000_sequential_usd": _r(cost_seq) if cost_seq is not None else None,
        "cost_per_1000_at_best_concurrency_usd": _r(cost_conc) if cost_conc is not None else None,
        "_scores": scores,
    }


ANSWER_PURPOSES = ("answer", "library_answer")


def call_metrics(records: list[dict]) -> dict:
    """Tokens each way and speed per call purpose, per question.

    From the per-call records (runs since 2026-10-15). Older runs have none:
    the answer rate is then approximated as the question's completion tokens
    over its answer-stage time (completion includes the side calls' few
    hundred tokens, so it reads slightly high) and marked "approx".
    """
    n = len(records) or 1
    with_calls = [r for r in records if r.get("calls")]
    if with_calls:
        by: dict[str, list[dict]] = defaultdict(list)
        for r in with_calls:
            for c in r["calls"]:
                by["answer" if c.get("purpose") in ANSWER_PURPOSES else "side"].append(c)

        def per_q(cs, key):
            return _r(sum(c.get(key) or 0 for c in cs) / len(with_calls))

        answer = by.get("answer", [])
        rates = [c["tok_s"] for c in answer if c.get("tok_s")]
        times = [c["ms"] for c in answer if c.get("ms") is not None]
        return {
            "source": "calls",
            "answer_tok_s_median": _r(statistics.median(rates)) if rates else None,
            "answer_ms_median": _r(statistics.median(times)) if times else None,
            "answer_prompt_tokens_per_q": per_q(answer, "prompt_tokens"),
            "answer_completion_tokens_per_q": per_q(answer, "completion_tokens"),
            "answer_reasoning_chars_per_q": per_q(answer, "reasoning_chars"),
            "answer_truncated": sum(1 for c in answer if c.get("finish_reason") == "length"),
            "side_prompt_tokens_per_q": per_q(by.get("side", []), "prompt_tokens"),
            "side_completion_tokens_per_q": per_q(by.get("side", []), "completion_tokens"),
        }
    rates = [r["completion_tokens"] / (r["step_ms"]["answer"] / 1000) for r in records
             if r.get("completion_tokens") and (r.get("step_ms") or {}).get("answer", 0) > 1]
    times = [r["step_ms"]["answer"] for r in records if (r.get("step_ms") or {}).get("answer")]
    return {
        "source": "approx",
        "answer_tok_s_median": _r(statistics.median(rates)) if rates else None,
        "answer_ms_median": _r(statistics.median(times)) if times else None,
        "answer_prompt_tokens_per_q": None, "answer_completion_tokens_per_q": None,
        "answer_reasoning_chars_per_q": _r(sum(r.get("reasoning_chars") or 0 for r in records) / n),
        "answer_truncated": None, "side_prompt_tokens_per_q": None, "side_completion_tokens_per_q": None,
    }

def compare(a: dict, b: dict) -> dict:
    """Paired comparison of configuration a against b on common questions."""
    common = sorted(set(a["_scores"]) & set(b["_scores"]))
    if not common:
        return {"questions": 0}
    pa = [statistics.mean(a["_scores"][q]) for q in common]
    pb = [statistics.mean(b["_scores"][q]) for q in common]
    diff, lo, hi = paired_bootstrap(pa, pb)
    only_a = sum(1 for q in common if majority(a["_scores"][q]) and not majority(b["_scores"][q]))
    only_b = sum(1 for q in common if majority(b["_scores"][q]) and not majority(a["_scores"][q]))
    return {"questions": len(common), "delta": _r(diff), "delta_ci": [_r(lo), _r(hi)],
            "only_a_correct": only_a, "only_b_correct": only_b, "mcnemar_p": _r(mcnemar_exact(only_a, only_b), 4)}


def _mean(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return _r(sum(vals) / len(vals)) if vals else None


def _r(value, digits: int = 3):
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else round(float(value), digits)


# --------------------------------------------------------------------------
# Report assembly
# --------------------------------------------------------------------------


def _rung_sort(key: str) -> tuple:
    rung = key.split("/")[0]
    return (RUNG_ORDER.index(rung) if rung in RUNG_ORDER else len(RUNG_ORDER), key)


def build_report(data: dict, baseline: str) -> dict:
    """report.json content: per-config summaries, pairwise tables, spend."""
    summaries = {}
    for key, cfg in data["configs"].items():
        cfg["key"] = key
        summaries[key] = summarise_config(cfg)
    ordered = sorted(summaries, key=_rung_sort)
    base = summaries.get(baseline)
    vs_baseline = {k: compare(summaries[k], base) for k in ordered if base and k != baseline}
    on_vs_off = {}
    for key in ordered:
        s = summaries[key]
        if s["condition"] == "on":
            off_key = key.replace("/on", "/off", 1)
            if off_key in summaries:
                on_vs_off[s["rung"]] = compare(s, summaries[off_key])
    spend_by_rung: dict[str, float] = defaultdict(float)
    for entry in data["ledger"]:
        spend_by_rung[entry.get("rung", "?")] += float(entry.get("session_cost_usd") or 0.0)
    public = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in summaries.items()}
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "baseline": baseline if base else None,
        "bootstrap_samples": BOOTSTRAP_SAMPLES, "seed": SEED,
        "configs": {k: public[k] for k in ordered},
        "vs_baseline": vs_baseline, "on_vs_off": on_vs_off,
        "spend": {"by_rung": {k: round(v, 2) for k, v in sorted(spend_by_rung.items())},
                  "total_usd": round(sum(spend_by_rung.values()), 2)},
        "_summaries": summaries,
    }


def _fmt(v, pct: bool = False) -> str:
    if v is None:
        return "—"
    if pct:
        return f"{100 * v:.1f}%"
    return f"{v}"


def render_markdown(report: dict, figures: list[str], figure_note: str) -> str:
    """REPORT.md: tables for every section, figures linked, narrative left for Phase 5."""
    cfgs = report["configs"]
    lines = ["# Evaluation report — model ladder on the golden set", "",
             f"Generated {report['generated']}. Baseline for comparisons: `{report['baseline']}`. "
             f"CIs: 95 % percentile bootstrap, {report['bootstrap_samples']:,} samples, seed {report['seed']}. "
             "Correctness = judge label *correct* on answerable questions, mean over repeats then over questions. "
             "In the paired tables the Δ and its CI use each question's mean over repeats; the only-X-right counts "
             "and McNemar use the majority vote over repeats (a tie counts as not correct).",
             "", "## Headline", "",
             "| Config | Model | Thinking | Path | Repeats | Correct | 95 % CI | Partial | Wrong | Abstained | "
             "Unanswerable declined | Faithful claims | Citations used | Source hit |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key, s in cfgs.items():
        ci = s["correct_ci"]
        lines.append(f"| {key} | {s['model']} | {s['thinking']} | {s['path']} | {s['repeats']} | "
                     f"{_fmt(s['correct_rate'], True)} | {_fmt(ci[0], True)}–{_fmt(ci[1], True)} | "
                     f"{s['partial']} | {s['wrong']} | {s['abstained']} | "
                     f"{_fmt(s['unanswerable']['declined_rate'], True)} | "
                     f"{_fmt(s['faithfulness']['supported_rate'], True)} | {_fmt(s['citations']['used_rate'], True)} | "
                     f"{_fmt(s['source_hit_rate'], True)} |")
    lines += ["", "## Against the baseline (paired by question)", "",
              "| Config | Questions | Δ correct | 95 % CI | Only this right | Only baseline right | McNemar p |",
              "|---|---|---|---|---|---|---|"]
    for key, c in report["vs_baseline"].items():
        if c.get("questions"):
            lines.append(f"| {key} | {c['questions']} | {_fmt(c['delta'], True)} | "
                         f"{_fmt(c['delta_ci'][0], True)}–{_fmt(c['delta_ci'][1], True)} | "
                         f"{c['only_a_correct']} | {c['only_b_correct']} | {c['mcnemar_p']} |")
    lines += ["", "## Thinking ON vs OFF (same rung, paired)", "",
              "| Rung | Questions | Δ correct (ON−OFF) | 95 % CI | Only ON right | Only OFF right | McNemar p |",
              "|---|---|---|---|---|---|---|"]
    for rung, c in report["on_vs_off"].items():
        if c.get("questions"):
            lines.append(f"| {rung} | {c['questions']} | {_fmt(c['delta'], True)} | "
                         f"{_fmt(c['delta_ci'][0], True)}–{_fmt(c['delta_ci'][1], True)} | "
                         f"{c['only_a_correct']} | {c['only_b_correct']} | {c['mcnemar_p']} |")
    cats = sorted({cat for s in cfgs.values() for cat in s["by_category"]})
    lines += ["", "## Correctness by category", "", "| Config | " + " | ".join(cats) + " |",
              "|---|" + "---|" * len(cats)]
    for key, s in cfgs.items():
        lines.append(f"| {key} | " + " | ".join(_fmt(s["by_category"].get(c), True) for c in cats) + " |")
    lines += ["", "## Retrieval (before generation)", "",
              "| Config | Recall@20 | Recall@8 | MRR | nDCG@8 | Page hit |", "|---|---|---|---|---|---|"]
    for key, s in cfgs.items():
        r = s["retrieval"]
        lines.append(f"| {key} | {_fmt(r['recall_at_20'])} | {_fmt(r['recall_at_8'])} | {_fmt(r['mrr'])} | "
                     f"{_fmt(r['ndcg_at_8'])} | {_fmt(r['page_hit'])} |")
    lines += ["", "## Speed and cost", "",
              "| Config | GPU | $/h | Boot s | Latency median s | p90 s | TTFT s | Decode tok/s | q/min @1/4/8 | "
              "Tokens/Q | Reasoning chars/Q | $/1,000 Q sequential | $/1,000 Q at best concurrency |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key, s in cfgs.items():
        qpm = " / ".join(_fmt(v) for v in s["questions_per_min"].values()) or "—"
        lines.append(f"| {key} | {s['gpu'] or '—'} | {_fmt(s['rate_usd_per_hr'])} | {_fmt(s['boot_s'])} | "
                     f"{_fmt(s['latency_median_s'])} | "
                     f"{_fmt(s['latency_p90_s'])} | {_fmt(s['ttft_median_s'])} | {_fmt(s['decode_tok_s_median'])} | "
                     f"{qpm} | {_fmt(s['tokens_per_question'])} | {_fmt(s['reasoning_chars_per_question'])} | "
                     f"{_fmt(s['cost_per_1000_sequential_usd'])} | "
                     f"{_fmt(s['cost_per_1000_at_best_concurrency_usd'])} |")
    lines += ["", "## Tokens and speed per model call", "",
              "Answer = the RAG or library answer call; side = pre-pass, memory and confidence calls. "
              "Tokens per second is end to end (includes prompt processing); \"approx\" rows predate "
              "per-call records and estimate it from the answer stage time.", "",
              "| Config | Source | Answer tok/s | Answer s | Answer prompt/Q | Answer completion/Q | "
              "Reasoning chars/Q | Truncated | Side prompt/Q | Side completion/Q |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for key, s in cfgs.items():
        c = s["calls"]
        lines.append(f"| {key} | {c['source']} | {_fmt(c['answer_tok_s_median'])} | "
                     f"{_fmt(c['answer_ms_median'] / 1000 if c['answer_ms_median'] else None)} | "
                     f"{_fmt(c['answer_prompt_tokens_per_q'])} | {_fmt(c['answer_completion_tokens_per_q'])} | "
                     f"{_fmt(c['answer_reasoning_chars_per_q'])} | {_fmt(c['answer_truncated'])} | "
                     f"{_fmt(c['side_prompt_tokens_per_q'])} | {_fmt(c['side_completion_tokens_per_q'])} |")
    lines += ["", "## Run health", "", "| Config | Errors | Think residue | Declined answers | Judged questions |",
              "|---|---|---|---|---|"]
    for key, s in cfgs.items():
        lines.append(f"| {key} | {s['errors']} | {s['think_residue']} | {s['declined_answers']} | "
                     f"{s['judged_questions']} |")
    lines += ["", "## Spend", "",
              "| Rung | USD |", "|---|---|"]
    for rung, usd in report["spend"]["by_rung"].items():
        lines.append(f"| {rung} | {usd} |")
    lines.append(f"| **total** | **{report['spend']['total_usd']}** |")
    lines += ["", "## Figures", ""]
    if figures:
        lines += [f"![{Path(f).stem}]({f})" for f in figures]
    else:
        lines.append(f"_No figures: {figure_note}_")
    lines += ["", "## Error taxonomy", "",
              "_Hand-labelled from the judge's wrong/partial set in Phase 5 (table misread, wrong row, "
              "retrieval miss, one side of a comparison, hallucinated value, format)._", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Figures (matplotlib, lazy)
# --------------------------------------------------------------------------


def draw_figures(report: dict, out_dir: Path) -> tuple[list[str], str]:
    """Write the SVG figures; returns (relative paths, note when none could be drawn)."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return [], "matplotlib is not installed (uv sync --extra dev)"
    cfgs = report["configs"]
    if not cfgs:
        return [], "no configurations"
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    def save(fig, name: str) -> None:
        path = fig_dir / f"{name}.svg"
        fig.tight_layout()
        fig.savefig(path, format="svg")
        plt.close(fig)
        written.append(f"figures/{name}.svg")

    # 1. correctness by rung, OFF and ON side by side, with CIs
    rungs = sorted({s["rung"] for s in cfgs.values()}, key=lambda r: _rung_sort(r + "/"))
    fig, ax = plt.subplots(figsize=(9, 4.5))
    width = 0.38
    for i, cond in enumerate(("off", "on")):
        xs, ys, errs = [], [], []
        for j, rung in enumerate(rungs):
            s = cfgs.get(f"{rung}/{cond}")
            if s and s["correct_rate"] is not None:
                xs.append(j + (i - 0.5) * width)
                ys.append(s["correct_rate"])
                errs.append([s["correct_rate"] - s["correct_ci"][0], s["correct_ci"][1] - s["correct_rate"]])
        if xs:
            ax.bar(xs, ys, width, yerr=np.array(errs).T, capsize=3, label=f"thinking {cond}")
    ax.set_xticks(range(len(rungs)))
    ax.set_xticklabels([f"{r}\n{(cfgs.get(f'{r}/off') or cfgs.get(f'{r}/on') or {}).get('model', '')}"
                        for r in rungs], fontsize=7)
    ax.set_ylim(0, 1)
    ax.set_ylabel("correct rate (answerable)")
    ax.set_title("Correctness by rung, 95 % bootstrap CI")
    ax.legend()
    save(fig, "correctness_by_rung")

    # 2. category heatmap
    cats = sorted({cat for s in cfgs.values() for cat in s["by_category"]})
    keys = list(cfgs)
    if cats:
        grid = np.array([[cfgs[k]["by_category"].get(c) if cfgs[k]["by_category"].get(c) is not None else np.nan
                          for c in cats] for k in keys])
        fig, ax = plt.subplots(figsize=(1.2 * len(cats) + 3, 0.4 * len(keys) + 2))
        im = ax.imshow(grid, vmin=0, vmax=1, cmap="viridis", aspect="auto")
        ax.set_xticks(range(len(cats)))
        ax.set_xticklabels(cats, rotation=30, ha="right")
        ax.set_yticks(range(len(keys)))
        ax.set_yticklabels(keys, fontsize=8)
        for i in range(len(keys)):
            for j in range(len(cats)):
                if not np.isnan(grid[i, j]):
                    ax.text(j, i, f"{grid[i, j]:.2f}", ha="center", va="center", fontsize=7,
                            color="white" if grid[i, j] < 0.5 else "black")
        fig.colorbar(im, ax=ax, label="correct rate")
        ax.set_title("Correctness by category")
        save(fig, "category_heatmap")

    # 3. thinking ON − OFF deltas
    if report["on_vs_off"]:
        fig, ax = plt.subplots(figsize=(7, 4))
        items = [(r, c) for r, c in report["on_vs_off"].items() if c.get("questions")]
        ax.axhline(0, color="grey", lw=0.8)
        ax.errorbar(range(len(items)), [c["delta"] for _r, c in items],
                    yerr=[[c["delta"] - c["delta_ci"][0] for _r, c in items],
                          [c["delta_ci"][1] - c["delta"] for _r, c in items]], fmt="o", capsize=4)
        ax.set_xticks(range(len(items)))
        ax.set_xticklabels([r for r, _c in items])
        ax.set_ylabel("Δ correct rate (ON − OFF)")
        ax.set_title("Effect of thinking per rung, paired 95 % CI")
        save(fig, "thinking_delta")

    # 4. latency vs correctness
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for key, s in cfgs.items():
        if s["latency_median_s"] is not None and s["correct_rate"] is not None:
            ax.scatter(s["latency_median_s"], s["correct_rate"], marker="o" if s["condition"] == "off" else "^")
            ax.annotate(key, (s["latency_median_s"], s["correct_rate"]), fontsize=7, xytext=(3, 3),
                        textcoords="offset points")
    ax.set_xlabel("median latency per question (s)")
    ax.set_ylabel("correct rate")
    ax.set_title("Quality vs latency (○ thinking off, △ on)")
    save(fig, "latency_vs_correctness")

    # 5. cost per 1,000 questions
    costed = [(k, s) for k, s in cfgs.items() if s["cost_per_1000_sequential_usd"] is not None]
    if costed:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar(range(len(costed)), [s["cost_per_1000_sequential_usd"] for _k, s in costed], label="sequential")
        conc = [s["cost_per_1000_at_best_concurrency_usd"] or 0 for _k, s in costed]
        if any(conc):
            ax.bar(range(len(costed)), conc, width=0.4, label="at best probe concurrency")
        ax.set_xticks(range(len(costed)))
        ax.set_xticklabels([k for k, _s in costed], rotation=30, ha="right", fontsize=7)
        ax.set_ylabel("USD per 1,000 questions")
        ax.set_title("Cost per 1,000 questions")
        ax.legend()
        save(fig, "cost_per_1000")

    # 6. retrieval recall@8 by category
    rcats = sorted({c for s in cfgs.values() for c in s["retrieval_recall_at_8_by_category"]})
    if rcats:
        fig, ax = plt.subplots(figsize=(8, 4))
        for key, s in cfgs.items():
            ax.plot(range(len(rcats)), [s["retrieval_recall_at_8_by_category"].get(c) for c in rcats],
                    marker="o", label=key, lw=1)
        ax.set_xticks(range(len(rcats)))
        ax.set_xticklabels(rcats, rotation=30, ha="right")
        ax.set_ylabel("recall@8")
        ax.set_title("Retrieval recall@8 by category")
        ax.legend(fontsize=6)
        save(fig, "retrieval_by_category")

    # 7. cards: cost vs throughput, when several GPUs ran
    carded = [(k, s) for k, s in cfgs.items() if "@" in k and s["questions_per_min"]]
    if len({s["gpu"] for _k, s in carded}) > 1:
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for key, s in carded:
            qpm = max(v for v in s["questions_per_min"].values() if v is not None)
            ax.scatter(s["rate_usd_per_hr"], qpm)
            ax.annotate(key, (s["rate_usd_per_hr"], qpm), fontsize=7, xytext=(3, 3), textcoords="offset points")
        ax.set_xlabel("USD per hour")
        ax.set_ylabel("best questions per minute")
        ax.set_title("Cards: price vs throughput")
        save(fig, "cards_cost_throughput")

    return written, ""


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate a campaign's results into report.json, figures and REPORT.md")
    parser.add_argument("campaign_dir", help="eval/results/<campaign>")
    parser.add_argument("--out-dir", default=None, help="Where to write (default: the campaign directory)")
    parser.add_argument("--baseline", default="r2/off", help="Configuration key the pairwise table compares against")
    parser.add_argument("--no-figures", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.campaign_dir)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 1
    out = Path(args.out_dir) if args.out_dir else root
    out.mkdir(parents=True, exist_ok=True)
    data = load_campaign_dir(root)
    if not data["configs"]:
        print(f"no runs found under {root}", file=sys.stderr)
        return 1
    report = build_report(data, args.baseline)
    figures, note = ([], "--no-figures") if args.no_figures else draw_figures(report, out)
    public = {k: v for k, v in report.items() if not k.startswith("_")}
    (out / "report.json").write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    (out / "REPORT.md").write_text(render_markdown(public, figures, note), encoding="utf-8")
    print(f"{len(report['configs'])} configuration(s); wrote {out / 'report.json'}, {out / 'REPORT.md'}"
          + (f", {len(figures)} figure(s)" if figures else f" (no figures: {note})"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
