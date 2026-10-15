"""scripts/eval_campaign.py — the gated rung runner on a fake console.

Uses the real campaign file for condition resolution, the script's own
FakeConsole for the pod state machine, and a stub command runner that logs
every command instead of running it. Covers: condition/session resolution,
the readiness rule, the spend gate, the pod-already-exists refusal, the
order of console calls, the ledger line, the .env restore, the pod-down
retry and the stuck-pod exit code, and the summary built from result files.
"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "eval_campaign.py"
spec = importlib.util.spec_from_file_location("eval_campaign_script", SCRIPT)
ec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ec)

CAMPAIGN = Path(__file__).resolve().parents[2] / "eval" / "campaign" / "eval-2026-10.toml"
# The real index check, kept before the autouse fixture stubs it out for rung tests.
_REAL_CHECK_INDEX = ec.check_index


def _campaign(tmp_path: Path) -> dict:
    """The real campaign file, with results and .env pointed into tmp_path."""
    c = ec.load_campaign(CAMPAIGN)
    c["campaign"]["results_dir"] = str(tmp_path / "results")
    c["campaign"]["ragline_env"] = str(tmp_path / "dotenv")
    c["campaign"]["podlink_dir"] = str(tmp_path / "podlink")
    # The runner checks that start.sh exists before calling it; the stub runner never runs it.
    (tmp_path / "podlink").mkdir(exist_ok=True)
    (tmp_path / "podlink" / "start.sh").write_text("#!/bin/sh\nexit 0\n")
    return c


@pytest.fixture(autouse=True)
def _index_present(monkeypatch):
    """Rung tests run against a stub index check (the real one queries Qdrant)."""
    monkeypatch.setattr(ec, "check_index", lambda campaign: None)


def _args(**kw) -> SimpleNamespace:
    base = dict(dry_run=False, skip_judge=True, skip_load=False, conditions=None, ids_file=None)
    base.update(kw)
    return SimpleNamespace(**base)


class Runner:
    """Stub for run_cmd: records commands, returns scripted exit codes."""

    def __init__(self, codes: dict | None = None):
        self.cmds: list[list[str]] = []
        self.envs: list[dict | None] = []
        self.codes = codes or {}

    def __call__(self, cmd, log, dry_run, env=None):
        self.cmds.append(cmd)
        self.envs.append(env)
        for key, code in self.codes.items():
            if any(key in part for part in cmd):
                return code
        return 0


# --- definition ---------------------------------------------------------------


def test_conditions_and_sessions_from_the_real_file():
    c = ec.load_campaign(CAMPAIGN)
    r2 = ec.resolve_conditions(c, c["rungs"]["r2"])
    assert [x["name"] for x in r2] == ["off", "on", "off-rag"]
    assert r2[0]["path"] == "chat" and r2[0]["repeats"] == 3 and r2[0]["load"] is True
    assert r2[2]["path"] == "rag" and r2[2]["repeats"] == 1 and r2[2]["load"] is False
    # ON (revised 2026-10-14): thinking for answers only, side calls off, 16k answer ceiling.
    on_env = r2[1]["env"]
    assert on_env["ANSWER_MAX_TOKENS"] == "16384" and on_env["LIBRARY_ANSWER_MAX_TOKENS"] == "16384"
    assert "true" in on_env["ANSWER_EXTRA_BODY"] and "false" in on_env["LLM_EXTRA_BODY"]
    # ON samples as Qwen recommends for thinking (never greedy); OFF leaves answers greedy.
    import json as _json
    on_body = _json.loads(on_env["ANSWER_EXTRA_BODY"].strip("'"))
    assert on_env["ANSWER_TEMPERATURE"] == "0.6" and on_body["top_p"] == 0.95 and on_body["top_k"] == 20
    assert on_body["min_p"] == 0 and r2[0]["env"]["ANSWER_TEMPERATURE"] == ""
    # OFF sends nothing extra on answer calls, so its requests are unchanged from rung 2's OFF run.
    assert r2[0]["env"]["ANSWER_EXTRA_BODY"] == "" and "false" in r2[0]["env"]["LLM_EXTRA_BODY"]
    assert len(ec.pod_sessions(r2)) == 1                                   # same profile throughout
    r3 = ec.resolve_conditions(c, c["rungs"]["r3"])
    sessions = ec.pod_sessions(r3)
    assert [s["profile"] for s in sessions] == ["eval-r3-qwen3-30b-a3b-2507-awq",
                                                "eval-r3-qwen3-30b-a3b-thinking-2507-fp8"]
    assert sessions[1]["conditions"][0]["separate_pod"] is True
    assert c["restore"]["env"] == {"LLM_EXTRA_BODY": "", "ANSWER_EXTRA_BODY": "", "ANSWER_TEMPERATURE": "",
                                   "ANSWER_MAX_TOKENS": "1500", "LIBRARY_ANSWER_MAX_TOKENS": "600"}


def test_is_ready_rule():
    base = {"state": "RUNNING", "services": {"llm": "healthy", "embedder": "healthy", "reranker": "healthy"},
            "test_result": {"all_ok": True}, "client_env": {"status": "written", "hook": "ok"}}
    assert ec.is_ready(base) == (True, "ready")
    assert ec.is_ready({**base, "state": "STARTING", "phase": "pod created"})[0] is False
    assert "reranker" in ec.is_ready({**base, "services": {**base["services"], "reranker": "pending"}})[1]
    assert "stack test" in ec.is_ready({**base, "test_result": {"all_ok": False}})[1]
    assert "hook" in ec.is_ready({**base, "client_env": {"status": "written", "hook": "exit 2"}})[1]


def test_ledger(tmp_path):
    ledger = tmp_path / "spend.jsonl"
    assert ec.ledger_total(ledger) == 0.0
    ec.ledger_append(ledger, {"session_cost_usd": 2.5})
    ec.ledger_append(ledger, {"session_cost_usd": 1.25})
    assert ec.ledger_total(ledger) == 3.75


def test_apply_env_uses_the_hook_merge(tmp_path):
    env = tmp_path / "dotenv"
    env.write_text("LLM_MODEL=x\nANSWER_MAX_TOKENS=1500\n")
    ec.apply_env(env, {"ANSWER_MAX_TOKENS": "5500", "LLM_EXTRA_BODY": "'{\"a\": 1}'"})
    text = env.read_text()
    assert "ANSWER_MAX_TOKENS=5500" in text and "ANSWER_MAX_TOKENS=1500" not in text
    assert "LLM_EXTRA_BODY='{\"a\": 1}'" in text and "LLM_MODEL=x" in text
    ec.apply_env(env, {"LIBRARY_ANSWER_MAX_TOKENS": "1"}, dry_run=True)
    assert "LIBRARY_ANSWER_MAX_TOKENS" not in env.read_text()


# --- the rung ------------------------------------------------------------------


def test_full_rung_happy_path(tmp_path):
    c = _campaign(tmp_path)
    env = Path(c["campaign"]["ragline_env"])
    env.write_text("ANSWER_MAX_TOKENS=1500\n")
    console = ec.FakeConsole(ready_after=3)
    runner = Runner()
    rc = ec.run_rung(c, "r2", console, _args(), runner=runner, sleep=lambda s: None)
    assert rc == 0
    # Console: connect, select, up, down — once each for the single session.
    assert console.calls == ["connect", "select:eval-r2-qwen3.8-27b-int4", "up", "down"]
    # Commands: preflight, then per condition evaluate (+ load except off-rag).
    names = [Path(cmd[1]).name if len(cmd) > 1 else cmd[0] for cmd in runner.cmds]
    assert names[0].endswith("start.sh") or "start.sh" in runner.cmds[0][0]
    # ... and the transcript archive after the rung ([archive] dest in the campaign file).
    assert names[1:] == ["evaluate.py", "eval_load.py", "evaluate.py", "eval_load.py", "evaluate.py",
                         "eval_archive.py"]
    ev_on = runner.cmds[3]
    assert "--condition" in ev_on and ev_on[ev_on.index("--condition") + 1] == "on"
    extra = json.loads(ev_on[ev_on.index("--manifest-extra") + 1])
    assert extra["rate_usd_per_hr"] == 2.09 and extra["model_id"] == "RedHatAI/Qwen3.8-27B-INT4"
    assert extra["condition_env"]["ANSWER_MAX_TOKENS"] == "16384"
    # Ledger has the session; .env restored; summary written.
    ledger = tmp_path / "results" / "eval-2026-10" / "spend.jsonl"
    entry = json.loads(ledger.read_text().splitlines()[0])
    assert entry["rung"] == "r2" and entry["session_cost_usd"] > 0 and entry["pod_stuck"] is False
    assert "ANSWER_MAX_TOKENS=1500" in env.read_text() and "LLM_EXTRA_BODY=" in env.read_text()
    summary = (tmp_path / "results" / "eval-2026-10" / "r2" / "SUMMARY.md").read_text()
    assert "| off-rag | rag | 0 |" in summary and "campaign to date" in summary


def test_spend_gate_and_existing_pod(tmp_path):
    c = _campaign(tmp_path)
    ledger = tmp_path / "results" / "eval-2026-10" / "spend.jsonl"
    ec.ledger_append(ledger, {"session_cost_usd": 250.0})
    assert ec.run_rung(c, "r2", ec.FakeConsole(), _args(), runner=Runner(), sleep=lambda s: None) == 3
    ledger.unlink()
    busy = ec.FakeConsole()
    busy.state, busy.pod_id = "RUNNING", "someone-elses-pod"
    assert ec.run_rung(c, "r2", busy, _args(), runner=Runner(), sleep=lambda s: None) == 4
    assert "up" not in busy.calls


def test_preflight_failure_stops_before_pod_up(tmp_path):
    c = _campaign(tmp_path)
    console = ec.FakeConsole()
    rc = ec.run_rung(c, "r2", console, _args(), runner=Runner({"start.sh": 1}), sleep=lambda s: None)
    assert rc == 5 and "up" not in console.calls


def test_create_failure_aborts_with_exit_code_and_down(tmp_path):
    """Pod creation fails (ERROR, no pod): exit 1, down still requested, .env restored."""
    c = _campaign(tmp_path)
    Path(c["campaign"]["ragline_env"]).write_text("")
    console = ec.FakeConsole(fail_start=True)
    rc = ec.run_rung(c, "r2", console, _args(), runner=Runner(), sleep=lambda s: None)
    assert rc == 1 and "down" in console.calls
    assert "LLM_EXTRA_BODY=" in Path(c["campaign"]["ragline_env"]).read_text()


def test_running_pod_that_never_becomes_ready_is_brought_down(tmp_path):
    """A pod that reaches RUNNING, bills, then fails before readiness is terminated and costed."""
    c = _campaign(tmp_path)
    Path(c["campaign"]["ragline_env"]).write_text("")
    console = ec.FakeConsole(fail_running=True)
    runner = Runner()
    rc = ec.run_rung(c, "r2", console, _args(), runner=runner, sleep=lambda s: None)
    assert rc == 1 and console.calls[-1] == "down" and console.state == "IDLE"
    # No condition ran, no judge ran, but the session's cost is in the ledger.
    assert not any("evaluate.py" in part for cmd in runner.cmds for part in cmd)
    entry = json.loads((tmp_path / "results" / "eval-2026-10" / "spend.jsonl").read_text().splitlines()[0])
    assert entry["session_cost_usd"] > 0 and entry["pod_stuck"] is False


def test_readiness_timeout_is_brought_down(tmp_path):
    """A pod that stays STARTING past the timeout is terminated, exit 1."""
    c = _campaign(tmp_path)
    Path(c["campaign"]["ragline_env"]).write_text("")
    console = ec.FakeConsole(ready_after=10**9)          # never ready within the test's timeout
    rc = ec.run_rung(c, "r2", console, _args(), runner=Runner(), sleep=lambda s: None, ready_timeout_s=0.05)
    assert rc == 1 and "down" in console.calls


def test_env_allow_list_and_newlines(tmp_path):
    """Only the campaign keys may reach .env; newlines are refused at every layer."""
    c = _campaign(tmp_path)
    c["conditions"]["on"]["env"]["AUTH_ENABLED"] = "false"
    c["restore"]["env"]["AUTH_ENABLED"] = "true"
    with pytest.raises(ec.CampaignError, match="allow-list"):
        ec.validate_campaign(c)
    env = tmp_path / "dotenv"
    env.write_text("")
    with pytest.raises(ec.CampaignError, match="allow-list"):
        ec.apply_env(env, {"SESSION_SECRET": "x"})
    assert env.read_text() == ""
    c = _campaign(tmp_path)
    c["conditions"]["on"]["env"]["ANSWER_MAX_TOKENS"] = "5500\nSESSION_SECRET=stolen"
    with pytest.raises(ec.CampaignError, match="newline"):
        ec.validate_campaign(c)
    with pytest.raises(ValueError, match="newline"):
        ec.apply_env(env, {"ANSWER_MAX_TOKENS": "1\nX=1"})


def test_validate_campaign_requires_restore_keys(tmp_path):
    c = _campaign(tmp_path)
    c["restore"]["env"].pop("ANSWER_MAX_TOKENS")
    with pytest.raises(ec.CampaignError, match="ANSWER_MAX_TOKENS"):
        ec.validate_campaign(c)
    with pytest.raises(ec.CampaignError):
        ec.run_rung(c, "r2", ec.FakeConsole(), _args(), runner=Runner(), sleep=lambda s: None)


def test_think_residue_and_stuck_pod_exit_codes(tmp_path):
    c = _campaign(tmp_path)
    Path(c["campaign"]["ragline_env"]).write_text("")
    # evaluate.py exits 2 (think residue) -> rung exit 2.
    rc = ec.run_rung(c, "r1", ec.FakeConsole(), _args(), runner=Runner({"evaluate.py": 2}), sleep=lambda s: None)
    assert rc == 2
    # Pod down refused more times than the retry budget -> exit 6 and a ledger line saying so.
    stuck = ec.FakeConsole(refuse_down=ec.DOWN_ATTEMPTS + 1)
    rc = ec.run_rung(c, "r1", stuck, _args(), runner=Runner(), sleep=lambda s: None)
    assert rc == 6
    lines = (tmp_path / "results" / "eval-2026-10" / "spend.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["pod_stuck"] is True
    # One refusal within the budget is retried and succeeds.
    retry = ec.FakeConsole(refuse_down=1)
    assert ec.run_rung(c, "r1", retry, _args(), runner=Runner(), sleep=lambda s: None) == 0
    assert retry.calls.count("down") == 2


def test_summary_reads_result_files(tmp_path):
    c = _campaign(tmp_path)
    root = ec.results_root(c, "r2") / "off"
    root.mkdir(parents=True)
    for n, hit in ((1, 0.8), (2, 0.9)):
        (root / f"r{n}.json").write_text(json.dumps({
            "hit_rate": hit, "latency_median_s": 5.0, "total_tokens": 1000, "total_reasoning_chars": 0,
            "think_residue": 0, "errors": 0, "retrieval_mean": {"recall_at_8": 0.7}}))
        (root / f"r{n}.judge.json").write_text(json.dumps({"summary": {"correct_rate_answerable": 0.75}}))
    (root / "load.json").write_text(json.dumps(
        {"end_to_end": [{"questions_per_min": 9.5}, {"questions_per_min": 20.0}]}))
    conds = ec.resolve_conditions(c, c["rungs"]["r2"])[:1]
    text = ec.rung_summary(c, "r2", c["rungs"]["r2"], conds, {"rung_usd": 5.1, "uptime_h": 2.4, "total_usd": 5.1},
                           {"off": 0})
    assert "| off | chat | 2 | 0.85 | 0.75 | 0.7 | 5.0 | 1000.0 | 0.0 | 0 | 0 | 9.5 / 20.0 | 0 |" in text
    assert "this rung: $5.1" in text and "--rung <next>" in text


# --- the frozen evaluation index ([index]) --------------------------------------


def test_index_pinned_into_eval_processes(tmp_path):
    """evaluate.py and eval_load.py get the index env; preflight and judge do not."""
    c = _campaign(tmp_path)
    Path(c["campaign"]["ragline_env"]).write_text("ANSWER_MAX_TOKENS=1500\n")
    runner = Runner()
    assert ec.run_rung(c, "r2", ec.FakeConsole(), _args(), runner=runner, sleep=lambda s: None) == 0
    pin = {"QDRANT_COLLECTION": "ragline_eval_v1", "DATABASE_URL": "sqlite+aiosqlite:///./data/ragline_eval_v1.db"}
    for cmd, env in zip(runner.cmds, runner.envs):
        name = Path(cmd[1]).name if len(cmd) > 1 else cmd[0]
        # Transcripts ([capture]) are switched on for evaluate runs only, never the probe.
        expected = {"evaluate.py": {**pin, "LLM_CAPTURE_TRANSCRIPTS": "1"}, "eval_load.py": pin}.get(name)
        assert env == expected


def test_missing_index_stops_before_pod_up(tmp_path, monkeypatch):
    """A failed index check is a preflight failure: exit 5, no console pod calls."""
    monkeypatch.setattr(ec, "check_index", lambda campaign: "collection 'ragline_eval_v1' does not exist")
    c = _campaign(tmp_path)
    console = ec.FakeConsole()
    assert ec.run_rung(c, "r2", console, _args(), runner=Runner(), sleep=lambda s: None) == 5
    assert console.calls == ["connect"]


@pytest.mark.parametrize("index", [
    {},
    {"collection": "bad name", "database_url": "sqlite+aiosqlite:///./data/x.db"},
    {"collection": "ok", "database_url": "postgresql://host/db"},
    {"collection": "ok", "database_url": "sqlite+aiosqlite:///./data/../../etc/x.db"},
    {"collection": "ok", "database_url": "sqlite+aiosqlite:///./data/x.db\nLLM_API_KEY=y"},
    {"collection": "ok\n", "database_url": "sqlite+aiosqlite:///./data/x.db"},
    {"collection": "ok", "database_url": "sqlite+aiosqlite:///./data/x.db\n"},
])
def test_validate_campaign_index_shape(tmp_path, index):
    c = _campaign(tmp_path)
    c["index"] = index
    with pytest.raises(ec.CampaignError):
        ec.validate_campaign(c)


def _qdrant(status: int, points: int | None = None):
    """An httpx client whose every GET answers like Qdrant's collection info."""
    import httpx
    body = {"result": {"points_count": points}} if points is not None else {}
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body)))


def test_check_index(tmp_path, monkeypatch):
    """Missing, empty, wrong-size collection and missing DB each name the problem."""
    c = _campaign(tmp_path)
    # Start from "no count recorded yet"; the real file records one (checked below).
    c["index"].pop("points", None)
    monkeypatch.setattr(ec, "REPO", tmp_path)
    (tmp_path / "data").mkdir()
    assert "does not exist" in _REAL_CHECK_INDEX(c, _qdrant(404))
    assert "empty" in _REAL_CHECK_INDEX(c, _qdrant(200, 0))
    assert "metadata DB" in _REAL_CHECK_INDEX(c, _qdrant(200, 15000))
    (tmp_path / "data" / "ragline_eval_v1.db").write_bytes(b"")
    assert _REAL_CHECK_INDEX(c, _qdrant(200, 15000)) is None
    c["index"]["points"] = 15001
    assert "froze 15001" in _REAL_CHECK_INDEX(c, _qdrant(200, 15000))


def test_real_campaign_freezes_the_eval_index():
    """The campaign file pins the built index: collection, DB and point count."""
    c = ec.load_campaign(CAMPAIGN)
    assert c["index"]["collection"] == "ragline_eval_v1" and c["index"]["points"] == 15064


def test_deferred_rungs_need_an_explicit_flag(capsys):
    """r1 and r1b are kept as a record but refused unless --include-deferred (dry run)."""
    c = ec.load_campaign(CAMPAIGN)
    assert c["rungs"]["r1"].get("deferred") and c["rungs"]["r1b"].get("deferred")
    assert not any(c["rungs"][r].get("deferred") for r in ("r2", "r3", "r4", "r5", "r6"))
    assert ec.main([str(CAMPAIGN), "--rung", "r1", "--dry-run"]) == 1
    assert "deferred" in capsys.readouterr().err
    assert ec.main([str(CAMPAIGN), "--rung", "r1", "--dry-run", "--include-deferred"]) == 0


# --- boot time per pod session (docs/eval/boot-vram-capture-plan.md) -----------


def test_boot_record_prefers_podlink_and_falls_back():
    """podlink's timeline wins; without it the runner's wall clock is used."""
    snap = {"boot_s": 828.0, "boot": {"up_requested": 1000.0, "running": 1182.0, "ready": 1828.0}}
    b = ec.boot_record(snap, 900.0)
    assert b == {"boot_s": 828.0, "boot_source": "podlink",
                 "boot_steps_s": {"up_requested": 0.0, "running": 182.0, "ready": 828.0}}
    b = ec.boot_record({}, 845.37)
    assert b == {"boot_s": 845.4, "boot_source": "runner", "boot_steps_s": {}}


def test_boot_lands_in_ledger_manifest_and_summary(tmp_path):
    """The rung records boot time in the ledger entry, every manifest and SUMMARY.md."""
    c = _campaign(tmp_path)
    Path(c["campaign"]["ragline_env"]).write_text("ANSWER_MAX_TOKENS=1500\n")
    runner = Runner()
    assert ec.run_rung(c, "r2", ec.FakeConsole(), _args(), runner=runner, sleep=lambda s: None) == 0
    entry = json.loads((tmp_path / "results" / "eval-2026-10" / "spend.jsonl").read_text().splitlines()[0])
    assert entry["boot"]["boot_s"] == 828.0 and entry["boot"]["boot_source"] == "podlink"
    ev = next(cmd for cmd in runner.cmds if len(cmd) > 1 and Path(cmd[1]).name == "evaluate.py")
    extra = json.loads(ev[ev.index("--manifest-extra") + 1])
    assert extra["boot_s"] == 828.0 and extra["boot_source"] == "podlink"
    summary = (tmp_path / "results" / "eval-2026-10" / "r2" / "SUMMARY.md").read_text()
    assert "## Pod sessions" in summary and "| eval-r2-qwen3.8-27b-int4 | 828.0 | podlink |" in summary


def test_boot_without_podlink_timeline(tmp_path):
    """An older console (no boot fields) still yields a boot time, marked as the runner's."""
    c = _campaign(tmp_path)
    Path(c["campaign"]["ragline_env"]).write_text("ANSWER_MAX_TOKENS=1500\n")
    assert ec.run_rung(c, "r2", ec.FakeConsole(with_boot=False), _args(), runner=Runner(),
                       sleep=lambda s: None) == 0
    entry = json.loads((tmp_path / "results" / "eval-2026-10" / "spend.jsonl").read_text().splitlines()[0])
    assert entry["boot"]["boot_source"] == "runner" and entry["boot"]["boot_s"] >= 0


def test_conditions_subset(tmp_path):
    """--conditions runs only the named conditions, in one pod session; unknown names refuse."""
    c = _campaign(tmp_path)
    Path(c["campaign"]["ragline_env"]).write_text("ANSWER_MAX_TOKENS=1500\n")
    runner = Runner()
    assert ec.run_rung(c, "r2", ec.FakeConsole(), _args(conditions="on,off-rag"), runner=runner,
                       sleep=lambda s: None) == 0
    conds = [cmd[cmd.index("--condition") + 1] for cmd in runner.cmds if "--condition" in cmd and
             Path(cmd[1]).name == "evaluate.py"]
    assert conds == ["on", "off-rag"]
    summary = (tmp_path / "results" / "eval-2026-10" / "r2" / "SUMMARY.md").read_text()
    assert "| off | chat |" in summary            # the summary still lists the whole rung
    console = ec.FakeConsole()
    assert ec.run_rung(c, "r2", console, _args(conditions="on,bogus"), runner=Runner(),
                       sleep=lambda s: None) == 1
    assert "up" not in console.calls


# --- a pod that dies mid-rung (2026-10-14: RunPod stopped the pod on low balance) ---


class _DyingConsole(ec.FakeConsole):
    """Ready as usual, then every service goes down once `die_after` status polls have passed."""

    def __init__(self, die_after: int, **kw):
        super().__init__(**kw)
        self.die_after = die_after

    def status(self) -> dict:
        snap = super().status()
        if snap.get("state") == "RUNNING" and self.polls > self.die_after:
            snap["services"] = {"llm": "down", "embedder": "down", "reranker": "down"}
        return snap


def test_pod_death_aborts_the_rung_and_still_brings_it_down(tmp_path):
    """No pass runs against a dead pod: the rung aborts, the pod is brought down, .env restored."""
    c = _campaign(tmp_path)
    env = Path(c["campaign"]["ragline_env"])
    env.write_text("ANSWER_MAX_TOKENS=1500\n")
    console = _DyingConsole(die_after=4)
    runner = Runner()
    rc = ec.run_rung(c, "r2", console, _args(), runner=runner, sleep=lambda s: None)
    assert rc == 1 and console.calls[-1] == "down"
    evals = [cmd for cmd in runner.cmds if len(cmd) > 1 and Path(cmd[1]).name == "evaluate.py"]
    assert len(evals) < 3                                   # stopped before running every condition
    assert "ANSWER_MAX_TOKENS=1500" in env.read_text() and "LLM_EXTRA_BODY=" in env.read_text()


def test_ids_file_is_forwarded_to_evaluate_only(tmp_path):
    """--ids-file lands on every evaluate.py invocation but not the throughput probe."""
    c = _campaign(tmp_path)
    Path(c["campaign"]["ragline_env"]).write_text("ANSWER_MAX_TOKENS=1500\n")
    # The ids file content is not read by the runner, only its path is forwarded.
    ids_file = tmp_path / "subset.txt"
    ids_file.write_text("A09\nD05\n")
    runner = Runner()
    rc = ec.run_rung(c, "r2", ec.FakeConsole(), _args(ids_file=str(ids_file)),
                     runner=runner, sleep=lambda s: None)
    assert rc == 0
    # Every evaluate.py invocation carries --ids-file with the given path;
    # eval_load.py (the probe) must not — load numbers stay on the full set.
    seen_on_evaluate = 0
    for cmd in runner.cmds:
        name = Path(cmd[1]).name if len(cmd) > 1 else cmd[0]
        if name == "evaluate.py":
            assert "--ids-file" in cmd
            assert cmd[cmd.index("--ids-file") + 1] == str(ids_file)
            seen_on_evaluate += 1
        else:
            assert "--ids-file" not in cmd
    # r2 has three conditions, so three evaluate.py calls carry the subset.
    assert seen_on_evaluate == 3


def test_sigterm_becomes_an_interrupt():
    """SIGTERM is turned into KeyboardInterrupt so the rung's finally blocks run."""
    with pytest.raises(KeyboardInterrupt):
        ec._terminate_as_interrupt(15, None)
