"""scripts/eval_judge.py — grading on a fake `claude` CLI.

A small executable named `claude` is put first on PATH; it reads the prompt,
answers from the items' text, and logs each call. That exercises batching,
the resumable judge file, the unanswerable mapping, retries, calibration
(kappa + confusion + exit code) and the second-opinion path with a fake
Codex caller. The statistics are checked by hand. No model is contacted.
"""

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "eval_judge.py"
spec = importlib.util.spec_from_file_location("eval_judge_script", SCRIPT)
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
prompt = sys.stdin.read()
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a") as fh:
        fh.write("call\n")
once = os.environ.get("FAKE_CLAUDE_FAIL_ONCE")
if once and not os.path.exists(once):
    open(once, "w").close()
    print(json.dumps({"is_error": True, "result": "rate limit reached, try later"}))
    sys.exit(1)
block = prompt.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
items = json.loads(block)
skip = os.environ.get("FAKE_CLAUDE_SKIP_ONCE")          # "<marker file>:<id>" — omit that id once
if skip:
    marker, skip_id = skip.rsplit(":", 1)
    if not os.path.exists(marker) and any(i["id"] == skip_id for i in items):
        open(marker, "w").close()
        items = [i for i in items if i["id"] != skip_id]
if "Judge task: correctness" in prompt:
    def verdict(i):
        a = i["answer"]
        return "abstained" if "couldn't" in a else ("wrong" if "WRONG" in a else "correct")
    out = {"items": [{"id": i["id"], "verdict": verdict(i), "reason": "fake"} for i in items]}
elif "Judge task: faithfulness" in prompt:
    out = {"items": [{"id": i["id"], "claims": [{"claim": "c", "supported": bool(i["passages"]),
                                                  "passage": 1 if i["passages"] else None}]} for i in items]}
else:
    out = {"items": [{"id": i["id"], "citations": [{"source": c["source"], "page": c["page"], "used": True}
                                                    for c in i["citations"]]} for i in items]}
print(json.dumps({"is_error": False, "structured_output": out, "total_cost_usd": 0.01, "duration_ms": 5,
                  "modelUsage": {"claude-opus-5-5": {"costUSD": 0.01}}}))
'''


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """Put a fake `claude` first on PATH; return the call-log path."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "claude"
    exe.write_text(FAKE_CLAUDE.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    return log


def _calls(log: Path) -> int:
    return len(log.read_text().splitlines()) if log.exists() else 0


def _golden(tmp_path: Path, n: int) -> Path:
    items = []
    for i in range(n):
        cat = "unanswerable" if i % 9 == 0 else "spec"
        items.append({"id": f"Q{i:02d}", "category": cat, "question": f"q{i}", "expected_answer": f"v{i}",
                      "evidence": [{"source": "hmi/x/a.pdf", "page": 3, "quote": f"v{i}"}]})
    p = tmp_path / "golden.json"
    p.write_text(json.dumps(items))
    return p


def _results(tmp_path: Path, n: int, name: str = "r1.json") -> Path:
    records = []
    for i in range(n):
        cat = "unanswerable" if i % 9 == 0 else "spec"
        # Unanswerables decline; every 7th answerable is marked wrong; the rest correct.
        answer = "I couldn't find it." if cat == "unanswerable" else (f"v{i} WRONG" if i % 7 == 0 else f"it is v{i}")
        records.append({
            "id": f"Q{i:02d}", "category": cat, "question": f"q{i}", "answer": answer, "expected_answer": f"v{i}",
            "cited_sources": ["a.pdf"], "cited_pages": [["a.pdf", 3]],
            "retrieval": {"reranked": [{"source": "a.pdf", "page_start": 3, "page_end": 3, "chunk_id": f"c{i}"}]},
        })
    p = tmp_path / name
    p.write_text(json.dumps({"run": {"golden_sha256": "abc"}, "per_question": records}))
    return p


# --- pure pieces -------------------------------------------------------------


def test_prompts_load_with_hashes():
    prompts = judge.load_prompts()
    assert set(prompts) == set(judge.TASKS)
    assert all(len(h) == 12 for _t, h in prompts.values())
    assert "near-miss is wrong" in prompts["correctness"][0]


def test_chunked_and_mapping():
    assert judge.chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert judge.map_unanswerable("unanswerable", "abstained") == "declined"
    assert judge.map_unanswerable("unanswerable", "correct") == "answered_wrong"
    assert judge.map_unanswerable("spec", "partial") == "partial"


def test_kappa_and_confusion_by_hand():
    """Observed 0.75, expected 0.3125 -> kappa 0.6364."""
    human = ["correct", "correct", "wrong", "abstained"]
    model = ["correct", "wrong", "wrong", "abstained"]
    assert judge.cohen_kappa(human, model) == 0.6364
    assert judge.cohen_kappa(human, human) == 1.0
    assert judge.cohen_kappa([], []) is None
    table = judge.confusion(human, model)
    assert table["correct"] == {"abstained": 0, "correct": 1, "wrong": 1}


def test_stratified_sample_is_deterministic():
    records = [{"id": f"S{i:02d}", "category": "spec"} for i in range(10)] + \
              [{"id": f"U{i:02d}", "category": "unanswerable"} for i in range(3)]
    sample = judge.stratified_sample(records, 0.2)
    assert sample == judge.stratified_sample(records, 0.2)
    assert sum(1 for s in sample if s.startswith("S")) == 2 and sum(1 for s in sample if s.startswith("U")) == 1


def test_item_builders():
    golden = {"Q1": {"category": "spec", "expected_answer": "8.4 W",
                     "evidence": [{"source": "hmi/x/a.pdf", "page": 26, "quote": "Max. 8.4 W"}]}}
    rec = {"id": "Q1", "question": "power?", "answer": "8.4 W [1]", "cited_sources": ["a.pdf"],
           "cited_pages": [["a.pdf", 26], ["a.pdf", 99]],
           "retrieval": {"reranked": [{"source": "a.pdf", "page_start": 25, "page_end": 26, "chunk_id": "c1"},
                                      {"source": "z.pdf", "page_start": 1, "page_end": 1, "chunk_id": "c2"}]}}
    ci = judge.correctness_items([rec], golden)[0]
    assert ci["evidence"] == [{"source": "a.pdf", "page": 26, "quote": "Max. 8.4 W"}]
    fi = judge.faithfulness_items([rec], {"c1": "text one", "c2": "text two"})[0]
    assert [p["n"] for p in fi["passages"]] == [1, 2] and fi["passages"][0]["text"] == "text one"
    cit = judge.citation_items([rec], {"c1": "text one"})[0]
    assert cit["citations"][0]["passage"] == "text one"       # page 26 inside chunk pages 25–26
    assert cit["citations"][1]["passage"] is None             # page 99: no chunk behind it
    prompt = judge.build_prompt("correctness", "RUBRIC", [ci])
    assert prompt.startswith("RUBRIC") and '"id": "Q1"' in prompt


# --- the CLI on the fake judge -----------------------------------------------


def test_batching_resume_and_force(tmp_path, fake_claude):
    """45 answers at batch 20 = 3 calls; a re-run makes none; --force grades again."""
    golden = _golden(tmp_path, 45)
    results = _results(tmp_path, 45)
    rc = judge.main([str(results), "--golden", str(golden), "--chunks", "none"])
    assert rc == 0 and _calls(fake_claude) == 3
    doc = json.loads(judge.judge_path(results).read_text())
    assert doc["tasks"]["correctness"]["calls"] == 3
    assert doc["per_question"]["Q00"]["correctness"]["label"] == "declined"      # unanswerable, abstained
    assert doc["per_question"]["Q07"]["correctness"]["label"] == "wrong"
    assert doc["per_question"]["Q01"]["correctness"]["label"] == "correct"
    assert doc["summary"]["verdicts"]["declined"] == 5
    assert "faithfulness" not in doc["tasks"]                                     # skipped: --chunks none

    assert judge.main([str(results), "--golden", str(golden), "--chunks", "none"]) == 0
    assert _calls(fake_claude) == 3                                                # resumed, nothing re-graded
    assert judge.main([str(results), "--golden", str(golden), "--chunks", "none", "--force"]) == 0
    assert _calls(fake_claude) == 6


def test_dry_run_calls_and_writes_nothing(tmp_path, fake_claude):
    golden = _golden(tmp_path, 5)
    results = _results(tmp_path, 5)
    assert judge.main([str(results), "--golden", str(golden), "--dry-run"]) == 0
    assert _calls(fake_claude) == 0 and not judge.judge_path(results).exists()


def test_call_claude_retries_on_failure(tmp_path, fake_claude, monkeypatch):
    """A throttled first attempt is retried; the metadata counts both."""
    monkeypatch.setenv("FAKE_CLAUDE_FAIL_ONCE", str(tmp_path / "failed-once"))
    waits = []
    prompt = judge.build_prompt("correctness", "Judge task: correctness",
                                [{"id": "Q1", "answer": "it is v1"}])
    output, meta = judge.call_claude(prompt, judge.SCHEMAS["correctness"], "m", sleep=waits.append)
    assert output["items"][0]["verdict"] == "correct"
    assert meta["attempts"] == 2 and waits == [180]              # throttle text -> the long wait


def test_calibration_kappa_and_exit_code(tmp_path, fake_claude):
    """Human grades that disagree with the fake judge drive kappa below the bar."""
    golden = _golden(tmp_path, 20)
    results = _results(tmp_path, 20)
    # Humans agree except on three answers the fake calls correct.
    grades = []
    for i in range(20):
        label = "declined" if i % 9 == 0 else ("wrong" if i % 7 == 0 else "correct")
        if label == "declined":
            label = "abstained"
        if i in (1, 2, 3):
            label = "wrong"
        grades.append({"id": f"Q{i:02d}", "label": label})
    gpath = tmp_path / "grades.json"
    gpath.write_text(json.dumps({"grades": grades}))
    rc = judge.main([str(results), "--golden", str(golden), "--calibrate", str(gpath), "--kappa-min", "0.9"])
    doc = json.loads(judge.judge_path(results).read_text())
    cal = doc["calibration"]
    assert cal["disagreements"] == ["Q01", "Q02", "Q03"]
    assert cal["kappa"] is not None and cal["kappa"] < 0.9 and rc == 1
    assert judge.main([str(results), "--golden", str(golden), "--calibrate", str(gpath), "--kappa-min", "0.5"]) == 0


def test_second_opinion_with_fake_codex(tmp_path, fake_claude):
    golden_path = _golden(tmp_path, 20)
    results = _results(tmp_path, 20)
    golden = {g["id"]: g for g in json.loads(golden_path.read_text())}
    prompts = judge.load_prompts()
    args = SimpleNamespace(tasks=["correctness"], model="m", batch=judge.DEFAULT_BATCH, chunks="none",
                           force=False, dry_run=False, sample=0.2, codex_state=str(tmp_path / "codex"))
    doc = judge.grade_file(results, golden, prompts, args, judge.call_claude)
    records = json.loads(results.read_text())["per_question"]

    def fake_codex(prompt, state):
        block = prompt.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
        # Codex agrees with everything except one id it calls partial.
        def verdict(i):
            if i["id"] == "Q01":
                return "partial"
            return "abstained" if "couldn't" in i["answer"] else ("wrong" if "WRONG" in i["answer"] else "correct")
        return {"items": [{"id": i["id"], "verdict": verdict(i), "reason": "codex"} for i in json.loads(block)]}

    so = judge.second_opinion(doc, records, golden, prompts, args, extra_ids=["Q01"], codex=fake_codex)
    assert "Q01" in so["sample_ids"] and so["codex_calls"] == 1
    assert doc["per_question"]["Q01"]["correctness_judge2"]["verdict"] == "partial"
    assert so["kappa_vs_judge"] is not None and so["kappa_vs_judge"] < 1.0


def test_resume_retries_only_errored_ids(tmp_path, fake_claude, monkeypatch):
    """An id the judge left without a verdict is retried alone on the next run, then counted."""
    golden = _golden(tmp_path, 45)
    results = _results(tmp_path, 45)
    monkeypatch.setenv("FAKE_CLAUDE_SKIP_ONCE", f"{tmp_path / 'skipped'}:Q04")
    assert judge.main([str(results), "--golden", str(golden), "--chunks", "none"]) == 0
    doc = json.loads(judge.judge_path(results).read_text())
    assert doc["per_question"]["Q04"]["correctness"] == {"error": "no verdict returned"}
    assert judge.pending_ids(doc, "correctness", doc["tasks"]["correctness"]["prompt_hash"],
                             [f"Q{i:02d}" for i in range(45)]) == ["Q04"]
    assert _calls(fake_claude) == 3
    # The re-run grades Q04 only: one more call, a real verdict, totals accumulated.
    assert judge.main([str(results), "--golden", str(golden), "--chunks", "none"]) == 0
    assert _calls(fake_claude) == 4
    doc = json.loads(judge.judge_path(results).read_text())
    assert doc["per_question"]["Q04"]["correctness"]["verdict"] == "correct"
    assert doc["tasks"]["correctness"]["calls"] == 4
    assert doc["per_question"]["Q01"]["correctness"]["verdict"] == "correct"     # others untouched
    # A third run has nothing left to do.
    assert judge.main([str(results), "--golden", str(golden), "--chunks", "none"]) == 0
    assert _calls(fake_claude) == 4


def test_tasks_only_pend_on_answers_they_apply_to(tmp_path, fake_claude, monkeypatch):
    """Answers that cite nothing get no citation-support item and never count as pending."""
    golden = _golden(tmp_path, 20)
    results = _results(tmp_path, 20)
    data = json.loads(results.read_text())
    for r in data["per_question"]:
        if r["category"] == "unanswerable":
            r["cited_sources"], r["cited_pages"] = [], []          # declined: nothing cited
    results.write_text(json.dumps(data))

    async def fake_texts(chunk_ids):
        return {cid: f"passage {cid}" for cid in chunk_ids}

    monkeypatch.setattr(judge, "fetch_chunk_texts", fake_texts)
    args = [str(results), "--golden", str(golden), "--tasks", "citation_support"]
    assert judge.main(args) == 0
    first = _calls(fake_claude)
    doc = json.loads(judge.judge_path(results).read_text())
    assert "citation_support" not in doc["per_question"].get("Q00", {})    # unanswerable, nothing to grade
    assert judge.main(args) == 0 and _calls(fake_claude) == first          # nothing pending on the re-run
