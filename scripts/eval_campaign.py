"""eval_campaign.py — run ONE gated rung of the evaluation campaign, end to end.

The per-rung protocol from docs/evaluation-plan.md (Phase 2), executed against
the podlink console on localhost — podlink keeps the cloud credentials; this
script only ever holds the console's per-run page token:

  1. spend gate — refuse when the campaign ledger is at/above `stop_ask_usd`
     (and when a pod already exists: bring it down first)
  2. preflight — the campaign's frozen index ([index]) must exist in Qdrant and
     on disk, and `start.sh --check --profile <rung profile>` must pass
  3. pod up — select the profile, POST /pod/up, poll /status until READY:
     state RUNNING, all three services healthy, the stack test all_ok, and
     the client-env handoff written with its hook (apply_pod_env.py, which
     merges the pod URLs into ragline's .env) reporting ok
  4. per condition (thinking OFF, then ON, …): merge the condition's variables
     into .env with the handoff hook's own merge routine, run evaluate.py
     (warm-up + repeats, campaign layout, manifest extras: GPU, rate, model,
     quantisation, vLLM reasoning parser), then eval_load.py
  5. pod down — terminate, wait for IDLE, read the session cost from the
     console and append it to eval/results/<campaign>/spend.jsonl
  6. offline — eval_judge.py over the rung's result files, then the rung
     SUMMARY.md with per-condition means and the spend to date
  7. exit — the next rung starts only when someone runs this again with the
     next --rung; nothing here chains rungs

A rung whose thinking-ON condition is a different checkpoint (rung 3) gets a
second pod session for it, automatically. The .env variables the conditions
change are restored to the campaign's `[restore]` values at the end, even on
failure. A pod that will not come down is reported in capitals with the
console state; it is never left silent.

Usage:
    python scripts/eval_campaign.py eval/campaign/eval-2026-10.toml --rung r2
    python scripts/eval_campaign.py eval/campaign/eval-2026-10.toml --rung r2 --dry-run
        (a fake console, commands printed, nothing written, no spend)

Exit codes: 0 done; 1 a run or the judge failed; 2 thinking text leaked
(evaluate.py exit 2) — the condition is invalid; 3 spend gate; 4 a pod
already exists; 5 preflight failed; 6 the pod did not come down — ACT NOW.
"""

import argparse
import fcntl
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))     # apply_pod_env: the same .env merge as the handoff hook
sys.path.insert(0, str(REPO / "src"))         # ragline.logging_utils: redaction for the campaign log

from ragline.logging_utils import redact_text  # noqa: E402

# The only .env keys a campaign may write. Everything else in .env (API keys,
# auth, ingest roots…) is out of reach of the campaign file by construction,
# so a careless or malicious condition cannot reconfigure the stack.
CAMPAIGN_ENV_KEYS = frozenset({"LLM_EXTRA_BODY", "ANSWER_EXTRA_BODY", "ANSWER_TEMPERATURE", "ANSWER_MAX_TOKENS",
                               "LIBRARY_ANSWER_MAX_TOKENS"})

# The frozen evaluation index ([index] in the campaign file). Its collection and
# metadata DB are pinned into the environment of every evaluate/load process,
# so no run can silently read the dev/prod index whatever .env says.
# \Z, not $: $ would also accept one trailing newline.
_COLLECTION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")
_DB_URL_RE = re.compile(r"^sqlite\+aiosqlite:///\./data/[A-Za-z0-9_.-]{1,64}\.db\Z")
_DB_URL_PREFIX = "sqlite+aiosqlite:///"

READY_POLL_S = 15
READY_TIMEOUT_S = 60 * 60       # first boot of a 65 GB checkpoint: download + load
DOWN_TIMEOUT_S = 15 * 60
DOWN_ATTEMPTS = 3
READY_STATES_OK = ("IDLE", "ERROR")           # states in which a new pod may be requested


class CampaignError(RuntimeError):
    """A step failed in a way the rung cannot continue from."""


# --------------------------------------------------------------------------
# Campaign definition (pure; tests/unit/test_eval_campaign.py)
# --------------------------------------------------------------------------


def load_campaign(path: Path) -> dict:
    """Parse the campaign TOML."""
    with path.open("rb") as fh:
        campaign = tomllib.load(fh)
    campaign["_path"] = str(path)          # for the gate instruction in SUMMARY.md
    return campaign


def validate_campaign(campaign: dict) -> None:
    """Fail fast on a campaign file that could leave .env in an eval state.

    Every key any condition writes to .env must be listed under `[restore].env`,
    otherwise the end-of-rung restore (a merge of those keys only) would leave
    the production stack in, say, thinking mode.
    """
    restore = set((campaign.get("restore") or {}).get("env") or {})
    used: set[str] = set()
    values: list[str] = []
    for cond in (campaign.get("conditions") or {}).values():
        used |= set(cond.get("env") or {})
        values += list((cond.get("env") or {}).values())
    for rung in (campaign.get("rungs") or {}).values():
        for extra in rung.get("extra_conditions", []):
            used |= set(extra.get("env") or {})
            values += list((extra.get("env") or {}).values())
    values += list(((campaign.get("restore") or {}).get("env") or {}).values())
    forbidden = sorted((used | restore) - CAMPAIGN_ENV_KEYS)
    if forbidden:
        raise CampaignError(f"campaign file: env keys outside the campaign allow-list {sorted(CAMPAIGN_ENV_KEYS)}: "
                            f"{forbidden}")
    if any("\n" in str(v) or "\r" in str(v) for v in values):
        raise CampaignError("campaign file: env values must not contain newlines")
    missing = sorted(used - restore)
    if missing:
        raise CampaignError(f"campaign file: condition env keys without a [restore] counterpart: {missing}")
    # [archive] dest, when set, must be an absolute path (it is passed to a subprocess).
    dest = (campaign.get("archive") or {}).get("dest")
    if dest is not None and (not isinstance(dest, str) or not dest.startswith("/") or "\n" in dest):
        raise CampaignError("campaign file: [archive].dest must be an absolute path")
    # The evaluation index must be named, and in a shape that cannot smuggle
    # anything else into the environment of the eval processes.
    index = campaign.get("index") or {}
    if not _COLLECTION_RE.match(str(index.get("collection", ""))):
        raise CampaignError("campaign file: [index].collection must be a plain Qdrant collection name")
    if not _DB_URL_RE.match(str(index.get("database_url", ""))):
        raise CampaignError("campaign file: [index].database_url must be sqlite+aiosqlite:///./data/<name>.db")


def index_env(campaign: dict) -> dict[str, str]:
    """Environment overrides that point ragline at the campaign's frozen index."""
    index = campaign["index"]
    # pydantic-settings ranks process environment above .env, so these win.
    return {"QDRANT_COLLECTION": index["collection"], "DATABASE_URL": index["database_url"]}


def check_index(campaign: dict, client: httpx.Client | None = None) -> str | None:
    """None when the campaign's index exists and looks right, else the reason it does not.

    Checks the Qdrant collection is present and non-empty (and, once recorded,
    holds exactly [index].points), and that the metadata DB file exists.
    """
    # Deferred import: reads .env only when a real rung runs.
    from ragline.config import settings

    index = campaign["index"]
    url = f"http://{settings.qdrant_host}:{settings.qdrant_port}/collections/{index['collection']}"
    try:
        # An injected client for tests, else a one-off request.
        resp = (client or httpx).get(url, timeout=10)
    except httpx.HTTPError as exc:
        return f"Qdrant not reachable at {settings.qdrant_host}:{settings.qdrant_port}: {exc}"
    if resp.status_code == 404:
        return f"Qdrant collection {index['collection']!r} does not exist"
    if resp.status_code != 200:
        return f"Qdrant answered {resp.status_code} for collection {index['collection']!r}"
    points = (resp.json().get("result") or {}).get("points_count") or 0
    if points == 0:
        return f"Qdrant collection {index['collection']!r} is empty"
    expected = index.get("points")
    if expected and points != expected:
        return f"Qdrant collection {index['collection']!r} has {points} points, the campaign froze {expected}"
    # The DB path is relative to the repo, as ragline resolves it from its cwd.
    db = REPO / index["database_url"][len(_DB_URL_PREFIX):]
    if not db.is_file():
        return f"metadata DB {db} does not exist"
    return None


def resolve_conditions(campaign: dict, rung: dict) -> list[dict]:
    """The rung's conditions, fully specified (name, env, path, repeats, load, profile, model).

    Named conditions take the campaign-wide definition; `extra_conditions`
    start from a named `base` and override fields — a different path,
    fewer repeats, no probe, or its own profile/model (a separate pod).
    """
    cfg = campaign["campaign"]
    defs = campaign["conditions"]

    def base(name: str) -> dict:
        return {
            "name": name, "env": dict(defs[name]["env"]), "path": cfg.get("path", "chat"),
            "repeats": cfg.get("repeats", 3), "load": True, "profile": rung["profile"],
            "model": rung["model"], "separate_pod": False,
        }

    out = [base(name) for name in rung.get("conditions", [])]
    for extra in rung.get("extra_conditions", []):
        cond = base(extra["base"])
        cond.update({k: v for k, v in extra.items() if k != "base"})
        out.append(cond)
    return out


def pod_sessions(conditions: list[dict]) -> list[dict]:
    """Group conditions into pod sessions: one per distinct profile, in order."""
    sessions: list[dict] = []
    for cond in conditions:
        key = cond["profile"]
        found = next((s for s in sessions if s["profile"] == key), None)
        if found is None:
            found = {"profile": key, "model": cond["model"], "conditions": []}
            sessions.append(found)
        found["conditions"].append(cond)
    return sessions


def is_ready(snapshot: dict) -> tuple[bool, str]:
    """The four readiness conditions; returns (ready, what is still missing)."""
    if snapshot.get("state") != "RUNNING":
        return False, f"state {snapshot.get('state')}: {snapshot.get('phase') or ''}".strip()
    services = snapshot.get("services") or {}
    pending = [name for name, status in services.items() if status != "healthy"]
    if pending or len(services) < 3:
        return False, f"services not healthy: {pending or 'none reported'}"
    test = snapshot.get("test_result") or {}
    if not test.get("all_ok"):
        return False, "stack test not passed" + (f" ({test.get('error')})" if test.get("error") else "")
    handoff = snapshot.get("client_env") or {}
    if handoff.get("status") != "written" or handoff.get("hook") != "ok":
        return False, f"client env handoff: {handoff.get('status')} / hook {handoff.get('hook')}"
    return True, "ready"


def ledger_total(path: Path) -> float:
    """Sum of session_cost_usd over the ledger lines (0 when there is none)."""
    if not path.exists():
        return 0.0
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            total += float(json.loads(line).get("session_cost_usd") or 0.0)
    return round(total, 4)


def ledger_append(path: Path, entry: dict) -> None:
    """Append one JSON line under an exclusive lock (a second runner must not interleave)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(entry) + "\n")
        fh.flush()
        fcntl.flock(fh, fcntl.LOCK_UN)


def apply_env(env_path: Path, updates: dict[str, str], dry_run: bool = False) -> None:
    """Merge KEY=VALUE updates into ragline's .env with the handoff hook's routine.

    Only CAMPAIGN_ENV_KEYS may be written (validate_campaign checks the file;
    this is the last line of defence at the write itself).
    """
    import apply_pod_env as hook

    bad = sorted(set(updates) - CAMPAIGN_ENV_KEYS)
    if bad:
        raise CampaignError(f"refusing to write .env keys outside the allow-list: {bad}")
    if dry_run:
        print(f"    [dry-run] would set {', '.join(sorted(updates))} in {env_path}")
        return
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    hook.write_env(env_path, hook.merge(text, updates))
    print(f"    .env: set {', '.join(sorted(updates))}")


def results_root(campaign: dict, rung_name: str) -> Path:
    cfg = campaign["campaign"]
    return REPO / cfg.get("results_dir", "eval/results") / cfg["name"] / rung_name


def evaluate_cmd(campaign: dict, rung_name: str, rung: dict, cond: dict, extra: dict,
                 ids_file: str | None = None) -> list[str]:
    """The evaluate.py invocation for one condition.

    `ids_file` (plan item 14): when the campaign runner was given `--ids-file`,
    every evaluate call carries it so each rung's conditions see the SAME
    question subset. The throughput probe stays on the full set — load tests
    are measured against the whole workload, not a slice.
    """
    cfg = campaign["campaign"]
    cmd = [
        sys.executable, str(REPO / "scripts" / "evaluate.py"), cfg["golden"],
        "--path", cond["path"], "--repeats", str(cond["repeats"]), "--warmup", str(cfg.get("warmup", 0)),
        "--campaign", cfg["name"], "--rung", rung_name, "--condition", cond["name"],
        "--output-dir", cfg.get("results_dir", "eval/results"),
        "--label", f"{cfg['name']}/{rung_name}/{cond['name']}",
        "--manifest-extra", json.dumps(extra),
    ]
    if ids_file:
        # Appended last so the preceding fixed layout stays easy to diff in the log.
        cmd += ["--ids-file", ids_file]
    return cmd


def load_cmd(campaign: dict, rung_name: str, cond: dict, extra: dict) -> list[str]:
    """The eval_load.py invocation for one condition."""
    cfg = campaign["campaign"]
    out = results_root(campaign, rung_name) / cond["name"] / "load.json"
    return [
        sys.executable, str(REPO / "scripts" / "eval_load.py"), cfg["golden"], "-o", str(out),
        "--levels", *[str(level) for level in cfg.get("load_levels", [1, 4, 8])],
        "--campaign", cfg["name"], "--rung", rung_name, "--condition", cond["name"],
        "--label", f"{cfg['name']}/{rung_name}/{cond['name']}",
        "--manifest-extra", json.dumps(extra),
    ]


def archive_cmd(campaign: dict, dest: str) -> list[str]:
    """The eval_archive.py invocation that copies the campaign's transcripts to `dest`."""
    cfg = campaign["campaign"]
    root = REPO / cfg.get("results_dir", "eval/results") / cfg["name"]
    return [sys.executable, str(REPO / "scripts" / "eval_archive.py"), "transcripts", str(root), "--dest", dest]


def judge_cmd(campaign: dict, files: list[Path]) -> list[str]:
    cfg = campaign["campaign"]
    return [sys.executable, str(REPO / "scripts" / "eval_judge.py"), *[str(f) for f in files],
            "--golden", cfg["golden"], "--model", cfg.get("judge_model", "claude-opus-5-5")]


def manifest_extra(campaign: dict, rung: dict, cond: dict, rate: float | None) -> dict:
    """What the harness cannot know by itself, recorded in every manifest."""
    cfg = campaign["campaign"]
    return {
        "gpu": cfg.get("gpu"), "cloud": cfg.get("cloud"), "rate_usd_per_hr": rate,
        "model_id": cond.get("model") or rung["model"], "quantization": rung.get("quantization"),
        "weights_gb": rung.get("weights_gb"), "reasoning_parser": rung.get("reasoning_parser"),
        "profile": cond["profile"], "condition_env": cond["env"], "rung_note": rung.get("note"),
    }


def boot_record(snap: dict, wall_s: float) -> dict:
    """Boot time of a pod session, for the ledger, the manifests and the summary.

    Prefers podlink's own timeline (`boot`, `boot_s` in /status: POD UP to ready,
    with each step). An older console without it falls back to the runner's own
    wall-clock measure from the POD UP request to readiness, which is coarser by
    up to one readiness poll (READY_POLL_S).
    """
    boot = snap.get("boot") or {}
    start = boot.get("up_requested")
    # Each step as seconds after POD UP, in the order the steps happened.
    steps = ({k: round(v - start, 1) for k, v in sorted(boot.items(), key=lambda kv: kv[1])}
             if isinstance(start, (int, float)) else {})
    if snap.get("boot_s") is not None:
        return {"boot_s": snap["boot_s"], "boot_source": "podlink", "boot_steps_s": steps}
    return {"boot_s": round(wall_s, 1), "boot_source": "runner", "boot_steps_s": steps}


# --------------------------------------------------------------------------
# Console client (podlink) and a fake for dry runs / tests
# --------------------------------------------------------------------------


class Console:
    """The podlink console over HTTP: status, profile select, pod up/down."""

    def __init__(self, base_url: str, client: httpx.Client | None = None):
        self.client = client or httpx.Client(base_url=base_url, timeout=30.0)
        self.token: str | None = None

    def connect(self) -> None:
        # The per-run page token gates every state-changing call.
        self.token = self.client.get("/config").json()["token"]

    def status(self) -> dict:
        return self.client.get("/status").json()

    def _post(self, path: str, body: dict) -> dict:
        response = self.client.post(path, json=body, headers={"x-podlink-token": self.token or ""})
        if response.status_code >= 400:
            raise CampaignError(f"{path} -> {response.status_code}: {response.text[:200]}")
        return response.json()

    def select_profile(self, name: str) -> dict:
        return self._post("/profile/select", {"profile": name})

    def pod_up(self) -> dict:
        return self._post("/pod/up", {"target": None})

    def pod_down(self) -> dict:
        # Terminate (not stop): weights live on the network volume.
        return self._post("/pod/down", {"confirm": True, "terminate": True})


class FakeConsole:
    """An in-memory console: ready after `ready_after` polls, down after one."""

    def __init__(self, ready_after: int = 2, fail_start: bool = False, refuse_down: int = 0, rate: float = 2.09,
                 fail_running: bool = False, with_boot: bool = True):
        self.ready_after, self.fail_start, self.refuse_down, self.rate = ready_after, fail_start, refuse_down, rate
        self.fail_running = fail_running                 # RUNNING, then a service dies -> ERROR
        self.with_boot = with_boot                       # False = an older console without the boot timeline
        self.state, self.pod_id, self.polls, self.calls = "IDLE", None, 0, []
        self.uptime = 0.0

    def connect(self) -> None:
        self.calls.append("connect")

    def status(self) -> dict:
        self.polls += 1
        snap = {"state": self.state, "phase": "", "pod_id": self.pod_id, "services": {}, "test_result": None,
                "client_env": None, "cost_per_hr": None, "session_cost_usd": None, "uptime_s": None, "error": None}
        if self.state == "STARTING":
            if self.fail_start:
                self.state = "ERROR"
                snap.update(state="ERROR", error="create failed: no stock")
            elif self.polls >= self.ready_after:
                self.state = "RUNNING"
        if self.state == "RUNNING" and self.fail_running:
            # The pod exists and bills, but never becomes ready: the caller
            # must still bring it down.
            self.state = "ERROR"
            snap.update(state="ERROR", error="llm service crashed", cost_per_hr=self.rate,
                        uptime_s=600.0, session_cost_usd=round(self.rate / 6, 4))
            return snap
        if self.state == "RUNNING":
            self.uptime += 600
            snap.update(state="RUNNING", services={"llm": "healthy", "embedder": "healthy", "reranker": "healthy"},
                        test_result={"all_ok": True}, client_env={"status": "written", "hook": "ok"},
                        cost_per_hr=self.rate, uptime_s=self.uptime,
                        session_cost_usd=round(self.rate * self.uptime / 3600, 4))
            if self.with_boot:
                # A 13-minute boot, as rung 2's was (podlink timeline shape).
                snap.update(boot={"up_requested": 1000.0, "created": 1004.0, "running": 1182.0,
                                  "services_healthy": 1784.0, "ready": 1828.0}, boot_s=828.0)
        if self.state == "ERROR" and self.pod_id:
            # The pod still exists (and bills) — the meter stays readable, as
            # podlink keeps it while a pod id is held.
            snap.update(cost_per_hr=self.rate, uptime_s=600.0, session_cost_usd=round(self.rate / 6, 4))
        if self.state == "STOPPING":
            self.state = "IDLE"
            self.pod_id = None
            snap.update(state="STOPPING")
        return snap

    def select_profile(self, name: str) -> dict:
        self.calls.append(f"select:{name}")
        return self.status()

    def pod_up(self) -> dict:
        self.calls.append("up")
        self.state, self.pod_id, self.polls = "STARTING", "fakepod", 0
        return self.status()

    def pod_down(self) -> dict:
        self.calls.append("down")
        if self.refuse_down > 0:
            self.refuse_down -= 1
            raise CampaignError("/pod/down -> 409: pod down not available in current state")
        self.state = "STOPPING"
        return self.status()


def require_ready(console) -> None:
    """Raise unless the pod is still fully ready — checked before every pass and probe.

    A pod can disappear mid-rung (RunPod stops pods when the account balance runs
    low; a host can fail). Without this the rung would run its remaining passes
    against a dead endpoint and record a file of errors; raising instead takes the
    normal abort path, so the pod is still brought down and the ledger written.
    """
    snap = console.status()
    ready, why = is_ready(snap)
    if not ready:
        raise CampaignError(f"pod no longer ready ({why}); aborting the rung")


def _terminate_as_interrupt(signum, frame) -> None:
    """SIGTERM -> KeyboardInterrupt, so a terminated runner still runs its cleanup."""
    raise KeyboardInterrupt(f"signal {signum}")


def wait_ready(console, timeout_s: float = READY_TIMEOUT_S, poll_s: float = READY_POLL_S, sleep=time.sleep) -> dict:
    """Poll /status until READY; raise on ERROR or timeout."""
    deadline = time.monotonic() + timeout_s
    last = ""
    while True:
        snap = console.status()
        if snap.get("state") == "ERROR":
            raise CampaignError(f"pod start failed: {snap.get('error') or snap.get('phase')}")
        ready, why = is_ready(snap)
        if ready:
            return snap
        if why != last:
            print(f"    waiting: {why}")
            last = why
        if time.monotonic() > deadline:
            raise CampaignError(f"pod not ready after {timeout_s:.0f}s: {why}")
        sleep(poll_s)


def bring_down(console, timeout_s: float = DOWN_TIMEOUT_S, poll_s: float = READY_POLL_S, sleep=time.sleep) -> dict:
    """Terminate the pod and wait for IDLE; returns the last status before down.

    Retries the down request DOWN_ATTEMPTS times. Raises CampaignError when
    the pod is still not down — the caller prints the banner.
    """
    before = console.status()
    error = ""
    for attempt in range(1, DOWN_ATTEMPTS + 1):
        try:
            console.pod_down()
        except CampaignError as exc:
            error = str(exc)
            print(f"    pod down attempt {attempt} refused: {error}")
            sleep(poll_s)
            continue
        deadline = time.monotonic() + timeout_s
        while time.monotonic() <= deadline:
            snap = console.status()
            if snap.get("state") == "IDLE" and not snap.get("pod_id"):
                return before
            if snap.get("state") == "ERROR":
                error = f"console ERROR during down: {snap.get('error')}"
                break
            sleep(poll_s)
        else:
            error = "timeout waiting for IDLE"
    raise CampaignError(f"pod did not come down: {error}")


# --------------------------------------------------------------------------
# Commands and the rung summary
# --------------------------------------------------------------------------


def run_cmd(cmd: list[str], log: Path | None, dry_run: bool, env: dict[str, str] | None = None) -> int:
    """Run a subprocess, teeing its output to `log`; prints the command first.

    `env` holds overrides layered on this process's environment (the index pin).
    """
    pin = " ".join(f"{k}={v}" for k, v in (env or {}).items())
    print("    $ " + (pin + " " if pin else "") + " ".join(shlex.quote(c) for c in cmd[:6])
          + (" …" if len(cmd) > 6 else ""))
    if dry_run:
        return 0
    with (log.open("a", encoding="utf-8") if log else open("/dev/null", "w")) as fh:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(REPO),
                                env={**os.environ, **(env or {})})
        assert proc.stdout is not None
        for line in proc.stdout:
            # The log lives under eval/results/ (publishable): pod hosts are
            # masked before anything is written or shown.
            clean = redact_text(line)
            sys.stdout.write(clean)
            fh.write(clean)
        return proc.wait()


def _mean(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def rung_summary(campaign: dict, rung_name: str, rung: dict, conditions: list[dict], spend: dict,
                 exit_codes: dict, boots: list[dict] | None = None) -> str:
    """SUMMARY.md for the gate: per-condition means over repeats, spend, judge grades."""
    root = results_root(campaign, rung_name)
    cfg = campaign["campaign"]
    lines = [f"# {cfg['name']} — rung {rung_name}: {rung['model']}", "",
             f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}. "
             f"{rung.get('note', '')}", "",
             "| Condition | Path | Repeats | Source hit | Correct (judge) | Recall@8 | Latency median s | "
             "Tokens/run | Reasoning chars/run | Think residue | Errors | q/min @1/4/8 | Exit |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for cond in conditions:
        cdir = root / cond["name"]
        runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(cdir.glob("r*.json"))
                if not p.name.endswith(".judge.json")]
        judges = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(cdir.glob("r*.judge.json"))]
        load = json.loads((cdir / "load.json").read_text(encoding="utf-8")) if (cdir / "load.json").exists() else None
        qpm = "—"
        if load:
            qpm = " / ".join(str(level.get("questions_per_min")) for level in load.get("end_to_end", []))
        lines.append(
            f"| {cond['name']} | {cond['path']} | {len(runs)} | "
            f"{_mean([r.get('hit_rate') for r in runs])} | "
            f"{_mean([j.get('summary', {}).get('correct_rate_answerable') for j in judges])} | "
            f"{_mean([r.get('retrieval_mean', {}).get('recall_at_8') for r in runs])} | "
            f"{_mean([r.get('latency_median_s') for r in runs])} | "
            f"{_mean([r.get('total_tokens') for r in runs])} | "
            f"{_mean([r.get('total_reasoning_chars') for r in runs])} | "
            f"{sum(r.get('think_residue', 0) for r in runs)} | {sum(r.get('errors', 0) for r in runs)} | "
            f"{qpm} | {exit_codes.get(cond['name'])} |"
        )
    # Boot time per pod session (POD UP to ready); GPU memory is not measured
    # automatically (docs/eval/boot-vram-capture-plan.md) and goes in NOTES.md.
    if boots:
        lines += ["", "## Pod sessions", "", "| Profile | Boot s | Source | Steps (s after POD UP) |",
                  "|---|---|---|---|"]
        for b in boots:
            steps = ", ".join(f"{k} {v}" for k, v in (b.get("boot_steps_s") or {}).items()) or "—"
            lines.append(f"| {b['profile']} | {b['boot_s']} | {b['boot_source']} | {steps} |")
    lines += ["", "## Spend", "",
              f"- this rung: ${spend.get('rung_usd')} ({spend.get('uptime_h')} h of pod time at the live rate)",
              f"- campaign to date: ${spend.get('total_usd')} of the ${cfg.get('budget_cap_usd')} cap "
              f"(stop-and-ask at ${cfg.get('stop_ask_usd')})",
              "", "## Gate", "",
              "Review the table and the judge files, then start the next rung with "
              f"`python scripts/eval_campaign.py {campaign.get('_path', '<campaign.toml>')} --rung <next>`. "
              "Nothing starts by itself.", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The rung
# --------------------------------------------------------------------------


def run_rung(campaign: dict, rung_name: str, console, args, runner=run_cmd, sleep=time.sleep,
             ready_timeout_s: float = READY_TIMEOUT_S) -> int:
    """Execute the protocol for one rung; returns the exit code."""
    validate_campaign(campaign)
    cfg = campaign["campaign"]
    rung = campaign["rungs"][rung_name]
    root = results_root(campaign, rung_name)
    ledger = root.parent / "spend.jsonl"
    env_path = REPO / cfg.get("ragline_env", ".env")
    log = None if args.dry_run else root / "campaign.log"
    if not args.dry_run:
        root.mkdir(parents=True, exist_ok=True)

    # 1. spend gate
    spent = ledger_total(ledger)
    if spent >= cfg.get("stop_ask_usd", 0):
        print(f"SPEND GATE: ${spent} already spent, at/above the stop-and-ask ${cfg.get('stop_ask_usd')}. "
              "Raise it in the campaign file after review to continue.")
        return 3
    console.connect()
    snap = console.status()
    if snap.get("state") not in READY_STATES_OK or snap.get("pod_id"):
        print(f"A POD ALREADY EXISTS (state {snap.get('state')}). Bring it down in the console first.")
        return 4

    # 2a. preflight — the frozen evaluation index must be there before any spend.
    if not args.dry_run:
        problem = check_index(campaign)
        if problem:
            print(f"PREFLIGHT FAILED: evaluation index — {problem}")
            return 5
    pinned = index_env(campaign)
    # Evaluation transcripts ([capture] transcripts = true): switched on for the
    # evaluate runs only — never the throughput probe or the judge, never .env.
    eval_env = {**pinned, **({"LLM_CAPTURE_TRANSCRIPTS": "1"}
                             if (campaign.get("capture") or {}).get("transcripts") else {})}

    all_conditions = resolve_conditions(campaign, rung)
    # --conditions runs a subset (e.g. to finish a rung a pod failure cut short);
    # the summary still lists every condition of the rung from the files on disk.
    wanted = [c.strip() for c in (getattr(args, "conditions", None) or "").split(",") if c.strip()]
    unknown = sorted(set(wanted) - {c["name"] for c in all_conditions})
    if unknown:
        print(f"unknown condition(s) for rung {rung_name}: {unknown}; "
              f"known: {[c['name'] for c in all_conditions]}")
        return 1
    conditions = [c for c in all_conditions if not wanted or c["name"] in wanted]
    sessions = pod_sessions(conditions)
    print(f"Rung {rung_name}: {rung['model']} — {len(conditions)} condition(s) in {len(sessions)} pod session(s); "
          f"spent so far ${spent}")

    exit_codes: dict[str, int] = {}
    boots: list[dict] = []                               # boot time per pod session, for the summary
    worst = 0
    rung_cost = 0.0
    rung_uptime = 0.0
    pod_stuck = False
    failed = False
    try:
        for session in sessions:
            # 2. preflight — start.sh must be a real file where the campaign says podlink is
            start_sh = (REPO / cfg.get("podlink_dir", "../podlink") / "start.sh").resolve()
            if not args.dry_run and not start_sh.is_file():
                print(f"PREFLIGHT FAILED: {start_sh} is not a file (campaign podlink_dir)")
                return 5
            check = [str(start_sh), "--check", "--profile", session["profile"]]
            if runner(check, log, args.dry_run) != 0:
                print(f"PREFLIGHT FAILED for profile {session['profile']}")
                return 5
            # 3. pod up — from here on the pod exists and bills, so EVERYTHING below,
            #    including the readiness wait, runs under the finally that brings it down.
            console.select_profile(session["profile"])
            up_at = time.time()                            # the runner's own boot clock (fallback)
            console.pod_up()
            print(f"    pod up requested with profile {session['profile']}; waiting for readiness")
            rate = None
            boot = None                                    # set once the pod is ready
            try:
                snap = wait_ready(console, sleep=sleep, poll_s=0 if args.dry_run else READY_POLL_S,
                                  timeout_s=ready_timeout_s)
                rate = snap.get("cost_per_hr")
                boot = boot_record(snap, time.time() - up_at)
                boots.append({"profile": session["profile"], **boot})
                print(f"    READY — rate ${rate}/h, boot {boot['boot_s']} s ({boot['boot_source']})")
                # 4. conditions
                for cond in session["conditions"]:
                    print(f"\n--- condition {cond['name']} ({cond['path']} path, {cond['repeats']} repeats) ---")
                    apply_env(env_path, cond["env"], args.dry_run)
                    extra = {**manifest_extra(campaign, rung, cond, rate),
                             "boot_s": boot["boot_s"], "boot_source": boot["boot_source"]}
                    require_ready(console)                 # never run a pass against a dead pod
                    # Forward the campaign-wide question subset to evaluate.py only
                    # (the throughput probe below runs against the full set).
                    ids_file = getattr(args, "ids_file", None)
                    rc = runner(evaluate_cmd(campaign, rung_name, rung, cond, extra, ids_file=ids_file),
                                log, args.dry_run, env=eval_env)
                    exit_codes[cond["name"]] = rc
                    worst = max(worst, rc if rc in (1, 2) else (1 if rc else 0))
                    if cond.get("load", True) and not args.skip_load:
                        require_ready(console)             # nor a probe
                        if runner(load_cmd(campaign, rung_name, cond, extra), log, args.dry_run,
                                  env=pinned) != 0:
                            print("    throughput probe failed (recorded, continuing)")
            except CampaignError as exc:
                # Readiness failed (ERROR, timeout) — the rung stops here, with an
                # exit code; the finally below still terminates the pod.
                print(f"    RUNG ABORTED: {exc}")
                failed = True
            finally:
                # 5. pod down + ledger, whatever happened above
                try:
                    before = bring_down(console, sleep=sleep, poll_s=0 if args.dry_run else READY_POLL_S)
                    cost = before.get("session_cost_usd") or 0.0
                    uptime = before.get("uptime_s") or 0.0
                    print(f"    pod down. session cost ${cost} for {uptime / 3600:.2f} h")
                except CampaignError as exc:
                    pod_stuck = True
                    cost, uptime = 0.0, 0.0
                    print(f"\n!!! POD STILL UP — {exc}. TERMINATE IT IN THE PODLINK CONSOLE OR THE RUNPOD "
                          "DASHBOARD NOW; IT IS BILLING. !!!\n")
                rung_cost += cost
                rung_uptime += uptime
                if not args.dry_run:
                    ledger_append(ledger, {
                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rung": rung_name,
                        "profile": session["profile"], "model": session["model"],
                        "conditions": [c["name"] for c in session["conditions"]],
                        "cost_per_hr": rate, "uptime_s": uptime, "session_cost_usd": cost,
                        "pod_stuck": pod_stuck, "boot": boot,
                    })
            if failed:
                break                                  # no further sessions after an abort
    finally:
        # Leave ragline's .env as production expects it.
        restore = campaign.get("restore", {}).get("env")
        if restore:
            apply_env(env_path, restore, args.dry_run)

    # 6. offline: judge + summary
    if not args.dry_run and not args.skip_judge and not failed:
        # Judge only what this invocation produced (other conditions were judged before).
        files = sorted(p for c in conditions for p in (root / c["name"]).glob("r*.json")
                       if not p.name.endswith(".judge.json"))
        if files and runner(judge_cmd(campaign, files), log, False) != 0:
            print("    judge failed (results are kept; re-run eval_judge.py by hand)")
            worst = max(worst, 1)
    # 6b. archive this rung's transcripts off the machine ([archive] dest), even after
    #     an abort — whatever was captured is kept. A failure is reported, not fatal.
    dest = (campaign.get("archive") or {}).get("dest")
    if dest and not args.dry_run:
        if runner(archive_cmd(campaign, dest), log, False) != 0:
            print("    transcript archive failed (files are still in eval/results; re-run eval_archive.py)")
    spend = {"rung_usd": round(rung_cost, 2), "uptime_h": round(rung_uptime / 3600, 2),
             "total_usd": ledger_total(ledger) if not args.dry_run else spent}
    summary = rung_summary(campaign, rung_name, rung, all_conditions, spend, exit_codes, boots)
    if args.dry_run:
        print("\n[dry-run] summary would be:\n" + summary)
    else:
        (root / "SUMMARY.md").write_text(summary, encoding="utf-8")
        print(f"\nSummary written to {root / 'SUMMARY.md'}")
    print(f"\nRung {rung_name} finished. Spend this rung ${spend['rung_usd']}, campaign ${spend['total_usd']}. "
          "STOP: review before the next rung.")
    return 6 if pod_stuck else (max(worst, 1) if failed else worst)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one gated rung of the evaluation campaign")
    parser.add_argument("campaign", help="Campaign TOML (eval/campaign/<name>.toml)")
    parser.add_argument("--rung", required=True, help="Rung name from the campaign file")
    parser.add_argument("--dry-run", action="store_true", help="Fake console, print commands, write nothing")
    parser.add_argument("--skip-judge", action="store_true", help="Leave grading for a separate eval_judge.py run")
    parser.add_argument("--skip-load", action="store_true", help="Skip the throughput probes")
    parser.add_argument("--console", default=None, help="Console URL (default from the campaign file)")
    parser.add_argument("--conditions", default=None,
                        help="Comma-separated subset of the rung's conditions to run (default: all)")
    parser.add_argument("--include-deferred", action="store_true",
                        help="Allow a rung marked deferred = true in the campaign file")
    # Subset forwarded to every evaluate.py call in this rung (plan item 14):
    # the throughput probe keeps the full set so load numbers stay comparable.
    parser.add_argument("--ids-file", default=None, dest="ids_file",
                        help="File with golden-set ids (one per line, `#` comments) — passed to evaluate.py")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    campaign = load_campaign(Path(args.campaign))
    if args.rung not in campaign["rungs"]:
        print(f"unknown rung {args.rung!r}; known: {', '.join(campaign['rungs'])}", file=sys.stderr)
        return 1
    # A deferred rung is kept in the file as a record but is out of the current
    # campaign: refuse it unless explicitly brought back, before any console call.
    if campaign["rungs"][args.rung].get("deferred") and not args.include_deferred:
        print(f"rung {args.rung!r} is deferred in the campaign file; pass --include-deferred to run it",
              file=sys.stderr)
        return 1
    console = FakeConsole() if args.dry_run else Console(args.console or campaign["campaign"]["console"])
    sleep = (lambda _s: None) if args.dry_run else time.sleep
    # Stop this process (not its shell wrapper, whose command line looks alike) with
    # SIGINT or SIGTERM: both run the cleanup — pod down, ledger, .env restore.
    signal.signal(signal.SIGTERM, _terminate_as_interrupt)
    print(f"runner pid {os.getpid()} (SIGINT/SIGTERM this pid to stop with cleanup)", flush=True)
    try:
        return run_rung(campaign, args.rung, console, args, sleep=sleep)
    except CampaignError as exc:
        print(f"CAMPAIGN ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
