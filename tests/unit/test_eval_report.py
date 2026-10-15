"""scripts/eval_report.py — statistics by hand and a report from synthetic runs.

The bootstrap and McNemar are checked on inputs with known answers; the
loader and the report are run on a small fake campaign directory (two rungs,
OFF and ON, judge files, a probe and a ledger) and the tables, pairwise
sections and files are asserted. Figures are drawn when matplotlib is
installed; the markdown must come out either way.
"""

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "eval_report.py"
spec = importlib.util.spec_from_file_location("eval_report_script", SCRIPT)
rep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rep)


# --- statistics ---------------------------------------------------------------


def test_bootstrap_ci_known_cases():
    mean, lo, hi = rep.bootstrap_ci([1.0] * 20)
    assert (mean, lo, hi) == (1.0, 1.0, 1.0)
    mean, lo, hi = rep.bootstrap_ci([1.0] * 50 + [0.0] * 50, samples=4000)
    assert mean == 0.5 and 0.38 < lo < 0.46 and 0.54 < hi < 0.62      # ≈ ±1.96·0.05
    # Reproducible: same seed, same interval.
    assert rep.bootstrap_ci([0.2, 0.9, 0.4, 0.7]) == rep.bootstrap_ci([0.2, 0.9, 0.4, 0.7])
    assert all(v != v for v in rep.bootstrap_ci([]))                   # NaN triple


def test_paired_bootstrap_and_mcnemar():
    diff, lo, hi = rep.paired_bootstrap([1, 1, 1, 0], [0, 1, 1, 0])
    assert diff == 0.25 and 0.0 <= lo <= diff <= hi <= 1.0
    # b=5, c=1: two-sided exact p = 2 * P(X <= 1 | n=6) = 2 * 7/64.
    assert rep.mcnemar_exact(5, 1) == 2 * 7 / 64
    assert rep.mcnemar_exact(0, 0) == 1.0
    assert rep.mcnemar_exact(3, 3) == 1.0
    assert rep.majority([1, 1, 0]) is True and rep.majority([1, 0]) is False


# --- a fake campaign ----------------------------------------------------------


QIDS = [f"A{i:02d}" for i in range(1, 11)] + ["E01", "E02"]


def _run(rung: str, cond: str, correct_ids: set[str], rate: float = 2.0, gpu: str = "GPU-X") -> tuple[dict, dict]:
    records, labels = [], {}
    for qid in QIDS:
        unans = qid.startswith("E")
        records.append({
            "id": qid, "category": "unanswerable" if unans else ("comparison" if qid in ("A09", "A10") else "spec"),
            "source_hit": None if unans else qid in correct_ids, "latency_s": 4.0 if cond == "off" else 9.0,
            "tokens": 1000, "reasoning_chars": 0 if cond == "off" else 2000, "declined": unans,
            "think_residue": False,
            "retrieval": {"recall_at_20": None if unans else 1.0, "recall_at_8": None if unans else 0.8,
                          "mrr": None if unans else 0.9, "ndcg_at_8": None if unans else 0.85,
                          "page_hit": None if unans else True},
        })
        if unans:
            labels[qid] = {"correctness": {"verdict": "abstained", "label": "declined"},
                           "faithfulness": {"claims": []}, "citation_support": {"citations": []}}
        else:
            label = "correct" if qid in correct_ids else "wrong"
            labels[qid] = {"correctness": {"verdict": label, "label": label},
                           "faithfulness": {"claims": [{"claim": "x", "supported": label == "correct", "passage": 1}]},
                           "citation_support": {"citations": [{"source": "a.pdf", "page": 1, "used": True}]}}
    run = {"run": {"rung": rung, "condition": cond, "thinking": cond, "path": "chat", "llm_model": f"model-{rung}",
                   "extra": {"gpu": gpu, "rate_usd_per_hr": rate, "model_id": f"model-{rung}", "quantization": "FP8",
                             "boot_s": 828.0 if rung == "r2" else None}},
           "hit_rate": len(correct_ids) / 10, "per_question": records}
    judge = {"per_question": labels, "summary": {}}
    return run, judge


def _campaign(tmp_path: Path) -> Path:
    root = tmp_path / "camp"
    plan = {
        ("r2", "off"): {"A01", "A02", "A03", "A04", "A05", "A06"},
        ("r2", "on"): {"A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08"},
        ("r1", "off"): {"A01", "A02", "A03"},
    }
    for (rung, cond), ids in plan.items():
        d = root / rung / cond
        d.mkdir(parents=True)
        for n in (1, 2):
            # Repeat 2 of r2/off loses A06, so that question scores 0.5.
            run, judge = _run(rung, cond, ids - ({"A06"} if (rung, cond, n) == ("r2", "off", 2) else set()))
            (d / f"r{n}.json").write_text(json.dumps(run))
            (d / f"r{n}.judge.json").write_text(json.dumps(judge))
        (d / "load.json").write_text(json.dumps({
            "end_to_end": [{"concurrency": 1, "questions_per_min": 12.0},
                           {"concurrency": 4, "questions_per_min": 30.0}],
            "streaming": [{"concurrency": 1, "ttft_s": {"median": 0.4}, "decode_tok_s": {"median": 80.0}}]}))
    (root / "spend.jsonl").write_text(json.dumps({"rung": "r2", "session_cost_usd": 5.5}) + "\n"
                                      + json.dumps({"rung": "r1", "session_cost_usd": 2.25}) + "\n")
    return root


def test_loader_and_summaries(tmp_path):
    root = _campaign(tmp_path)
    data = rep.load_campaign_dir(root)
    assert sorted(data["configs"]) == ["r1/off", "r2/off", "r2/on"]
    report = rep.build_report(data, "r2/off")
    s = report["configs"]["r2/off"]
    # 10 answerable: five fully correct, A06 half (lost in repeat 2) -> 0.55.
    assert s["correct_rate"] == 0.55 and s["correct_ci"][0] < 0.55 < s["correct_ci"][1]
    assert s["repeats"] == 2 and s["judged_questions"] == 10
    assert s["unanswerable"] == {"n": 4, "declined": 4, "answered_wrong": 0, "declined_rate": 1.0}
    assert s["by_category"]["comparison"] == 0.0 and s["by_category"]["spec"] == 0.688
    assert s["faithfulness"]["supported_rate"] == 0.55 and s["citations"]["used_rate"] == 1.0
    assert s["retrieval"]["recall_at_8"] == 0.8 and s["questions_per_min"] == {"1": 12.0, "4": 30.0}
    assert s["ttft_median_s"] == 0.4 and s["latency_median_s"] == 4.0
    assert s["boot_s"] == 828.0 and report["configs"]["r1/off"]["boot_s"] is None
    # Cost: $2/h, 4 s per question sequential -> 2 * 4/3600 * 1000 = 2.222; at 30 q/min -> 2/1800*1000 = 1.111.
    assert s["cost_per_1000_sequential_usd"] == 2.222 and s["cost_per_1000_at_best_concurrency_usd"] == 1.111
    # Pairwise: r2/on adds A07, A08 and never loses A06 -> delta = +0.25. Majority vote over two
    # repeats: A06 (1 of 2) is a tie = not correct for OFF, so only-on-right = 3 (A06, A07, A08).
    on = report["on_vs_off"]["r2"]
    assert on["questions"] == 10 and on["delta"] == 0.25 and on["only_a_correct"] == 3 and on["only_b_correct"] == 0
    vs = report["vs_baseline"]["r1/off"]
    assert vs["delta"] == -0.25 and vs["only_b_correct"] == 2 and vs["mcnemar_p"] == 0.5   # A04, A05; A06 is a tie
    assert report["spend"] == {"by_rung": {"r1": 2.25, "r2": 5.5}, "total_usd": 7.75}


def test_main_writes_report_and_figures(tmp_path):
    root = _campaign(tmp_path)
    assert rep.main([str(root)]) == 0
    md = (root / "REPORT.md").read_text()
    assert "| r2/off | model-r2 | off | chat | 2 | 55.0% |" in md
    assert "## Thinking ON vs OFF" in md and "| r2 | 10 | 25.0% |" in md
    assert "| **total** | **7.75** |" in md
    doc = json.loads((root / "report.json").read_text())
    assert doc["baseline"] == "r2/off" and "_summaries" not in doc
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        assert "_No figures" in md
    else:
        figs = sorted(p.name for p in (root / "figures").glob("*.svg"))
        assert {"correctness_by_rung.svg", "category_heatmap.svg", "thinking_delta.svg",
                "latency_vs_correctness.svg", "cost_per_1000.svg", "retrieval_by_category.svg"} <= set(figs)
        assert "![correctness_by_rung](figures/correctness_by_rung.svg)" in md
    assert rep.main([str(root), "--no-figures", "--out-dir", str(tmp_path / "out")]) == 0
    assert "_No figures: --no-figures_" in (tmp_path / "out" / "REPORT.md").read_text()
