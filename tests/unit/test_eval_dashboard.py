"""scripts/eval_dashboard.py — data build and page render on the synthetic campaign.

Reuses the fake campaign of test_eval_report.py (two rungs, OFF and ON, judge
files, a probe and a ledger) plus a diagnosis and measurements file, and checks
the dashboard's own additions and that the page embeds the data.
"""

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1] / "scripts"


def _load(path: Path, name: str):
    """Load a module from a file path."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dash = _load(SCRIPTS / "eval_dashboard.py", "eval_dashboard_script")
fixture = _load(HERE / "test_eval_report.py", "eval_report_fixture")


def _golden(tmp_path: Path) -> Path:
    """A golden file for the fixture's question ids."""
    path = tmp_path / "golden.json"
    path.write_text(json.dumps([{"id": q, "expected_answer": f"value {q}", "tags": ["t"]} for q in fixture.QIDS]))
    return path


def test_build_data_adds_dashboard_views(tmp_path):
    """Half-partial credit, verdict mix, stability, diagnosis rollup and per-question cells."""
    root = fixture._campaign(tmp_path)
    (root / "r2" / "diagnosis.json").write_text(json.dumps({"rung": "r2", "questions": [
        {"id": "A09", "causes": ["RET-CHUNK", "PARSE"], "evidence_reached_model": "never", "explanation": "x",
         "proposed_fix": "y", "ragline_fixable": True, "model_independent": True, "golden_or_judge_note": ""}]}))
    (root / "measurements.toml").write_text('[[r2.session]]\nconditions = ["off"]\nvram_gib = 48\ncard_gib = 96\n')
    data = dash.build_data(root, "r2/off", _golden(tmp_path))
    off = data["configs"]["r2/off"]
    assert off["correct_rate"] == 0.55 and off["verdict_mix"]["correct"] + off["verdict_mix"]["wrong"] == 1.0
    assert off["stable_questions"] == 11 and off["questions"] == 12          # A06 flips between the two repeats
    assert data["diagnosis"]["n"] == 1 and [list(p) for p in data["diagnosis"]["primary"]] == [["RET-CHUNK", 1]]
    q = next(x for x in data["questions"] if x["id"] == "A06")
    assert [c["label"] for c in q["cells"]["r2/off"]] == ["correct", "wrong"] and q["expected"] == "value A06"
    assert data["measurements"]["r2"]["session"][0]["vram_gib"] == 48


def test_render_embeds_data_safely(tmp_path):
    """The placeholder is replaced and a closing script tag in the data cannot end the script."""
    template = tmp_path / "t.html"
    template.write_text("<script>const DATA = /*__DATA__*/null;</script>")
    page = dash.render({"answer": "</script><b>x</b>"}, template)
    assert "/*__DATA__*/" not in page and "</script><b>" not in page and "<\\/script>" in page


def test_main_writes_page(tmp_path):
    """The CLI writes the page next to the results by default."""
    root = fixture._campaign(tmp_path)
    assert dash.main([str(root), "--golden", str(_golden(tmp_path))]) == 0
    page = (root / "dashboard.html").read_text()
    assert "Ragline model ladder" in page and '"campaign": "camp"' in page


def _campaign_file(tmp_path: Path) -> Path:
    """A campaign file: r2 and r3 active, r1 deferred, a verification rung."""
    path = tmp_path / "campaign.toml"
    path.write_text('[rungs.r3]\nmodel = "m3"\nconditions = ["off", "on"]\n'
                    '[rungs.r1]\nmodel = "m1"\ndeferred = true\n'
                    '[rungs.r2-s1]\nmodel = "m2"\n'
                    '[rungs.r2]\nmodel = "m2"\nconditions = ["off", "on"]\n')
    return path


def test_ladder_tabs_run_order_with_repeat(tmp_path):
    """r2 first, deferred and verification rungs left out, a closing r2 repeat."""
    tabs = dash.load_ladder(_campaign_file(tmp_path), [])
    assert [t["rung"] for t in tabs] == ["r2", "r3", "r2-repeat"]
    assert tabs[1]["planned"] == dash.PLANNED and tabs[2]["planned"] == dash.REPEAT


def test_public_build_drops_spend_pods_and_verification_runs(tmp_path):
    """The shareable copy carries no ledger, no pod ids and only ladder rungs; the private one tabs everything."""
    root = fixture._campaign(tmp_path)
    (root / "measurements.toml").write_text(
        '[[r2.session]]\nconditions = ["off"]\npod = "abc123"\nvram_gib = 48\ncard_gib = 96\n')
    private = dash.build_data(root, "r2/off", _golden(tmp_path), _campaign_file(tmp_path))
    public = dash.build_data(root, "r2/off", _golden(tmp_path), _campaign_file(tmp_path), public=True)
    assert "spend" in private and "spend" not in public
    assert "abc123" not in json.dumps(public) and "abc123" in json.dumps(private)
    assert {c["rung"] for c in public["configs"].values()} <= {"r2", "r3"}
    assert all(set(q["cells"]) <= set(public["configs"]) for q in public["questions"])
    assert {t["rung"] for t in private["ladder"]} >= {c["rung"] for c in private["configs"].values()}


def test_wrap_public_is_a_full_document_with_card_tags():
    """Doctype, charset, viewport and Open Graph image at the site URL; the styles stay in <head>."""
    page = dash.wrap_public("<title>T</title>\n<style>a{}</style>\n<div>x</div>", "https://example.org/ragline")
    assert page.startswith("<!doctype html>") and '<meta charset="utf-8">' in page
    assert 'content="https://example.org/ragline/og.png"' in page
    assert page.index("</style>") < page.index("</head>") < page.index("<div>x</div>") < page.index("</body>")
