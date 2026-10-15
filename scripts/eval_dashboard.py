"""eval_dashboard.py — build the evaluation dashboard (one self-contained HTML page).

    python scripts/eval_dashboard.py eval/results/eval-2026-10 [-o PATH] [--baseline r2/off]
    python scripts/eval_dashboard.py eval/results/eval-2026-10 --public --site-url URL -o site/index.html

Reads what the campaign directory holds — results and judge files per
rung/condition, the throughput probes, the spend ledger, `measurements.toml`
(hand readings: GPU memory, host, driver) and each rung's `diagnosis.json` —
reuses scripts/eval_report.py for every statistic (so the page and REPORT.md
agree), and writes one HTML file with the data embedded and the charts drawn
in the page. The same file is kept locally (default:
<campaign>/dashboard.html) and published as the private claude.ai page.
Sections follow docs/eval/results-presentation-plan.md: decide the
configuration, thinking on/off, what to fix in ragline, trust, explore.

The page has one tab per rung of the campaign ladder (from the campaign file,
deferred rungs left out), in run order, plus a closing "r2 repeat" tab;
rungs with no results yet show what is planned for them. `--public` builds
the shareable copy: only ladder rungs (no verification runs), no spend ledger
and no pod ids in the embedded data, and a full HTML document with link-card
(Open Graph) tags for `--site-url`.
"""

import argparse
import importlib.util
import json
import statistics
import tomllib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The report script holds the statistics; load it as a module.
_spec = importlib.util.spec_from_file_location("eval_report_for_dashboard", HERE / "eval_report.py")
rep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rep)

# Verdict labels in display order; "declined" / "answered_wrong" are the unanswerable outcomes.
VERDICTS = ["correct", "partial", "wrong", "abstained"]
# The campaign's standing, shown on every tab; updated as the campaign moves on.
STATUS = ("In progress. Rung 2 is complete and serves as ragline's initial-state baseline: "
          "the faults it exposed in ragline itself (retrieval, parsing, prompts) are being fixed "
          "and verified before rungs 3 to 6 run on the fixed ragline. Rung 2 is then repeated "
          "for a direct before/after comparison.")
# What an un-run rung's tab says.
PLANNED = ("Planned. Runs after ragline's own fixes are verified, on the fixed ragline and the "
           "rebuilt evaluation index: 3 passes with thinking off and 3 with thinking on over the "
           "100-question golden set, judged the same way as rung 2.")
REPEAT = ("Planned. Rung 2's model re-run on the fixed ragline at the end of the campaign, so the "
          "gain from ragline's own fixes and the differences between models can be read apart.")
# Judge calibration against the 46 hand grades (scripts/eval_judge.py --calibrate, 2026-10-13).
JUDGE_CALIBRATION = {"kappa": 0.883, "agree": 44, "of": 46, "source": "eval/human_grades_2026-09-28.json, 2026-10-13"}


def _labels(judge: dict) -> dict[str, str | None]:
    """Question id -> correctness label in one judge file."""
    return {q: (e.get("correctness") or {}).get("label") for q, e in judge.get("per_question", {}).items()}


def _score(label: str | None, half_partial: bool) -> float:
    """1 for correct, 0.5 for partial when half credit applies, else 0."""
    return 1.0 if label == "correct" else (0.5 if half_partial and label == "partial" else 0.0)


def config_extras(cfg: dict) -> dict:
    """What the dashboard needs beyond eval_report's summary for one configuration."""
    records = [r for run in cfg["runs"] for r in run["per_question"]]
    cats = {r["id"]: r.get("category") for r in records}
    labels = [_labels(j) for j in cfg["judges"] if j]
    answerable = sorted(q for q in cats if cats[q] != "unanswerable")
    # Correct with half credit for partial, per question then averaged, with a bootstrap CI.
    per_q = [statistics.mean(_score(lab.get(q), True) for lab in labels) for q in answerable if labels]
    half = rep.bootstrap_ci(per_q) if per_q else (None, None, None)
    # Verdict mix over all repeats (answerable questions).
    mix = Counter(lab.get(q) for lab in labels for q in answerable)
    total = sum(mix.values()) or 1
    # Stability: same label in every repeat.
    stable = sum(1 for q in cats if len({lab.get(q) for lab in labels}) == 1) if labels else None
    # Reasoning length by verdict (thinking runs only carry reasoning).
    by_verdict = defaultdict(list)
    for run, lab in zip(cfg["runs"], labels):
        for r in run["per_question"]:
            if cats.get(r["id"]) != "unanswerable" and (r.get("reasoning_chars") or 0) > 0:
                by_verdict[lab.get(r["id"])].append(r["reasoning_chars"])
    # Median ms per pipeline stage, averaged over the repeats' medians.
    stages = defaultdict(list)
    for run in cfg["runs"]:
        for name, ms in (run.get("step_ms_median") or {}).items():
            stages[name].append(ms)
    return {
        "correct_half_partial": rep._r(half[0]) if half[0] is not None else None,
        "correct_half_partial_ci": [rep._r(half[1]), rep._r(half[2])] if half[0] is not None else None,
        "verdict_mix": {v: round(mix.get(v, 0) / total, 3) for v in VERDICTS},
        "stable_questions": stable, "questions": len(cats),
        "reasoning_by_verdict": {v: int(statistics.median(xs)) for v, xs in by_verdict.items() if v and xs},
        "stage_ms": {k: round(statistics.mean(v), 1) for k, v in stages.items()},
    }


def question_rows(data: dict, golden: dict, diagnoses: dict) -> list[dict]:
    """One row per golden question: per configuration and repeat, the verdict and its detail."""
    rows = {}
    for key, cfg in data["configs"].items():
        labels = [_labels(j) for j in cfg["judges"] if j]
        reasons = [{q: (e.get("correctness") or {}).get("reason") for q, e in j.get("per_question", {}).items()}
                   for j in cfg["judges"] if j]
        for i, run in enumerate(cfg["runs"]):
            for r in run["per_question"]:
                g = golden.get(r["id"], {})
                row = rows.setdefault(r["id"], {
                    "id": r["id"], "category": r.get("category"), "question": r.get("question"),
                    "expected": g.get("expected_answer", r.get("expected_answer")), "tags": g.get("tags", []),
                    "diagnosis": diagnoses.get(r["id"]), "cells": {}})
                row["cells"].setdefault(key, []).append({
                    "label": labels[i].get(r["id"]) if i < len(labels) else None,
                    "reason": (reasons[i].get(r["id"]) or "")[:400] if i < len(reasons) else "",
                    "answer": (r.get("answer") or "").strip()[:900],
                    "cited": r.get("cited_sources") or [],
                    "latency_s": r.get("latency_s"), "reasoning_chars": r.get("reasoning_chars") or 0,
                    "recall_at_8": (r.get("retrieval") or {}).get("recall_at_8"),
                })
    return sorted(rows.values(), key=lambda x: x["id"])


def load_diagnoses(root: Path) -> dict:
    """Question id -> diagnosis, from every rung's diagnosis.json (latest rung wins)."""
    out = {}
    for path in sorted(root.glob("*/diagnosis.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for q in doc.get("questions", []):
            out[q["id"]] = {"rung": doc.get("rung"), "causes": q.get("causes", []),
                            "reached": q.get("evidence_reached_model"), "explanation": q.get("explanation"),
                            "fix": q.get("proposed_fix"), "fixable": q.get("ragline_fixable"),
                            "model_independent": q.get("model_independent"),
                            "note": q.get("golden_or_judge_note") or ""}
    return out


def load_ladder(campaign_file: Path | None, found_rungs: list[str]) -> list[dict]:
    """The tabs: active rungs in campaign order, then the closing r2 repeat.

    Without a campaign file the tabs are just the rungs that have results.
    """
    if campaign_file is None or not campaign_file.is_file():
        return [{"rung": r, "title": r} for r in found_rungs]
    rungs = tomllib.loads(campaign_file.read_text(encoding="utf-8")).get("rungs", {})
    # Verification rungs (r2-s1, …) are not ladder rungs; deferred ones are out of the campaign.
    active = {k: v for k, v in rungs.items() if not v.get("deferred") and "-" not in k}
    # r2 runs first (the baseline), the rest in numeric order.
    order = sorted(active, key=lambda k: (k != "r2", k))
    tabs = [{"rung": k, "title": f"Rung {k[1:]}", "model": v.get("model"),
             "quantization": v.get("quantization"), "weights_gb": v.get("weights_gb"),
             "conditions": v.get("conditions", []) + [c["name"] for c in v.get("extra_conditions", [])
                                                      if c.get("load", True) is not False],
             "note": v.get("note", ""), "planned": PLANNED} for k, v in ((k, active[k]) for k in order)]
    if "r2" in active:
        tabs.append({**tabs[0], "rung": "r2-repeat", "title": "Rung 2 repeat", "planned": REPEAT,
                     "note": "Same model and settings as rung 2."})
    return tabs


def build_data(root: Path, baseline: str, golden_path: Path, campaign_file: Path | None = None,
               public: bool = False) -> dict:
    """Everything the page renders, as one JSON-able dict."""
    data = rep.load_campaign_dir(root)
    report = rep.build_report(data, baseline)
    golden = {q["id"]: q for q in json.loads(golden_path.read_text(encoding="utf-8"))}
    diagnoses = load_diagnoses(root)
    mpath = root / "measurements.toml"
    # Hand readings per pod session (GPU memory, host, driver), when recorded.
    measurements = tomllib.loads(mpath.read_text()) if mpath.is_file() else {}
    configs = {}
    for key, summary in report["configs"].items():
        configs[key] = {**summary, **config_extras(data["configs"][key])}
    # Diagnosis rollups for "what to fix".
    diag = list(diagnoses.values())
    found = sorted({c["rung"] for c in configs.values()}, key=lambda r: (r != "r2", r))
    ladder = load_ladder(campaign_file, found)
    if public:
        # Shareable copy: ladder rungs only (verification runs stay private), no pod ids.
        tab_rungs = {t["rung"] for t in ladder}
        configs = {k: v for k, v in configs.items() if v["rung"] in tab_rungs}
        measurements = {r: {"session": [{k: v for k, v in s.items() if k != "pod"} for s in m.get("session", [])]}
                        for r, m in measurements.items() if r in tab_rungs}
    else:
        # The private page also gets a tab per verification run (r2-s1, …) after the ladder.
        ladder += [{"rung": r, "title": f"{r} (verification)"} for r in found if r not in {t["rung"] for t in ladder}]
    out = {
        "campaign": root.name,
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "baseline": baseline,
        "configs": configs,
        "order": [k for k in report["configs"] if k in configs],
        "on_vs_off": {r: v for r, v in report["on_vs_off"].items() if any(c["rung"] == r for c in configs.values())},
        "vs_baseline": {k: v for k, v in report["vs_baseline"].items() if k in configs},
        "measurements": measurements,
        "judge": JUDGE_CALIBRATION,
        "status": STATUS,
        "ladder": ladder,
        "questions": question_rows(data, golden, diagnoses),
        "diagnosis": {
            "n": len(diag),
            "primary": Counter(d["causes"][0] for d in diag if d["causes"]).most_common(),
            "present": Counter(c for d in diag for c in set(d["causes"])).most_common(),
            "reached": Counter(d["reached"] for d in diag).most_common(),
            "fixable": sum(1 for d in diag if d["fixable"]),
            "model_independent": sum(1 for d in diag if d["model_independent"]),
        },
    }
    if public:
        # Per-question cells only for the configurations on the page.
        for q in out["questions"]:
            q["cells"] = {k: v for k, v in q["cells"].items() if k in configs}
    else:
        # The private page keeps the ledger in its data (not shown on the page).
        out["spend"] = report["spend"]
    return out


# Wrapper for the public copy: a full document (the claude.ai page supplies its own).
PUBLIC_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{desc}">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{url}og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{url}og.png">
"""
PUBLIC_TITLE = "Ragline model ladder — RAG evaluation"
PUBLIC_DESC = ("Interactive evaluation of ragline, a citation-first RAG system for industrial HMI manuals: "
               "LLMs from 27B to 122B on one RTX PRO 6000, thinking on vs off, judged on a 100-question golden set.")


def wrap_public(page: str, site_url: str) -> str:
    """The page as a complete document with link-card tags (site_url ends with /)."""
    url = site_url if site_url.endswith("/") else site_url + "/"
    head = PUBLIC_HEAD.format(title=PUBLIC_TITLE, desc=PUBLIC_DESC, url=url)
    # The template opens with its <title>; everything up to </style> belongs in <head>.
    cut = page.index("</style>") + len("</style>")
    return head + page[:cut] + "\n</head>\n<body>\n" + page[cut:] + "\n</body>\n</html>\n"


def render(data: dict, template: Path) -> str:
    """The page: the template with the data embedded (closing-tag-safe)."""
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return template.read_text(encoding="utf-8").replace("/*__DATA__*/null", blob)


def main(argv: list[str] | None = None) -> int:
    """Parse args, build the data, write the page."""
    parser = argparse.ArgumentParser(description="Build the evaluation dashboard HTML")
    parser.add_argument("campaign_dir", help="e.g. eval/results/eval-2026-10")
    parser.add_argument("-o", "--output", default=None, help="Output HTML (default <campaign>/dashboard.html)")
    parser.add_argument("--baseline", default="r2/off", help="Configuration other rows are compared with")
    parser.add_argument("--golden", default="eval/golden_set_hmi.json")
    parser.add_argument("--campaign-file", default=None,
                        help="Campaign TOML for the rung tabs (default eval/campaign/<campaign dir name>.toml)")
    parser.add_argument("--public", action="store_true",
                        help="Shareable copy: ladder rungs only, no spend or pod ids, "
                             "full document with link-card tags")
    parser.add_argument("--site-url", default="https://14mm47.github.io/ragline/",
                        help="Where the public copy is served (for the link-card tags)")
    args = parser.parse_args(argv)
    root = Path(args.campaign_dir)
    out = Path(args.output) if args.output else root / "dashboard.html"
    campaign_file = Path(args.campaign_file) if args.campaign_file else Path("eval/campaign") / f"{root.name}.toml"
    data = build_data(root, args.baseline, Path(args.golden), campaign_file, public=args.public)
    page = render(data, HERE / "eval_dashboard_template.html")
    if args.public:
        page = wrap_public(page, args.site_url)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"dashboard written to {out} ({len(page) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
