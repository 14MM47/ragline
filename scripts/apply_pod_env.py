#!/usr/bin/env python3
"""Apply a podlink client-env block to ragline's .env and restart ragline.

podlink runs this as its PODLINK_CLIENT_ENV_HOOK — `apply_pod_env.py <env_file>` —
right after it has proven the pod healthy (its stack test passed) and written the
block: live service URLs, the bearer, the served embedding dimension and any
per-profile extras. It also works by hand, with the same argument.

What it does, in order:
  1. Parse the block; keep only the keys ragline's pod wiring owns (ALLOWED_KEYS).
     A block with an unfilled bearer placeholder or no LLM_BASE_URL is refused.
  2. Merge into .env: each allowed key's existing line is replaced in place
     (everything else in .env is untouched); new keys are appended under a
     marker. The previous .env is kept as .env.bak (same mode). Written
     atomically, mode preserved (0600 for a new file).
  3. Restart ragline — the LLM/embedder/reranker clients are built once at
     startup, so a URL change needs a new process:
       RAGLINE_APPLY_RESTART=auto (default): `systemctl restart ragline` when
         that unit exists, else ./restart.sh detached (dev); systemd | dev | none
         force one. The dev log goes to data/logs/ragline-dev.log.
  4. Wait for GET /api/health to report status "ok" (RAGLINE_HEALTH_URL,
     RAGLINE_HEALTH_TIMEOUT_S, default 120 s). Exit 0 when it does, 2 when it
     does not — podlink shows the hook's exit code, never its output.

Nothing here imports ragline (stdlib only) and no secret value is ever printed:
only key names and statuses.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "# --- podlink handoff (managed by scripts/apply_pod_env.py) ---"

# The keys a pod block may set. Anything else in the block is ignored (and
# named on stderr), so a stray line can never rewrite auth or storage settings.
ALLOWED_KEYS = frozenset({
    "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY",
    "EMBEDDING_BASE_URL", "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS", "EMBEDDING_API_KEY",
    "RERANKER_PROVIDER", "RERANKER_BASE_URL", "RERANKER_API_KEY", "RERANKER_API_FORMAT",
    "KG_EXTRACTION_CONCURRENCY",
})
# podlink omits RERANKER_API_FORMAT for a TEI reranker (its default); switching
# back from a vLLM/cohere stack must reset it, so an absent key means its default.
DEFAULTS_WHEN_ABSENT = {"RERANKER_API_FORMAT": "tei"}
PLACEHOLDER_HINT = "<your "


def parse_block(text: str) -> dict[str, str]:
    """KEY=VALUE lines -> dict, comments/blank lines skipped, keys filtered."""
    found: dict[str, str] = {}
    skipped: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            continue
        if key in ALLOWED_KEYS:
            found[key] = value.strip()
        else:
            skipped.append(key)
    if skipped:
        print(f"ignored keys not owned by the pod wiring: {', '.join(sorted(set(skipped)))}", file=sys.stderr)
    if "LLM_BASE_URL" not in found:
        raise SystemExit("refusing: block has no LLM_BASE_URL — not a podlink client block")
    if any(PLACEHOLDER_HINT in v for v in found.values()):
        raise SystemExit("refusing: block still carries a placeholder (bearer not filled in)")
    for key, default in DEFAULTS_WHEN_ABSENT.items():
        found.setdefault(key, default)
    return found


def merge(env_text: str, updates: dict[str, str]) -> str:
    """Replace each key's first `KEY=` line in place; append the rest under MARKER."""
    lines = env_text.splitlines()
    pending = dict(updates)
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else None
        if key in pending:
            lines[i] = f"{key}={pending.pop(key)}"
    if pending:
        if lines and lines[-1].strip():
            lines.append("")
        if MARKER not in lines:
            lines.append(MARKER)
        for key in sorted(pending):
            lines.append(f"{key}={pending[key]}")
    return "\n".join(lines) + "\n"


def write_env(env_path: Path, text: str) -> None:
    """Back up, then replace atomically with the same mode (0600 for a new file)."""
    mode = stat.S_IMODE(env_path.stat().st_mode) if env_path.exists() else 0o600
    if env_path.exists():
        backup = env_path.with_name(env_path.name + ".bak")
        shutil.copy2(env_path, backup)
        os.chmod(backup, mode)
    fd, tmp = tempfile.mkstemp(prefix=f".{env_path.name}.", dir=env_path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, env_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _systemd_unit_exists(unit: str) -> bool:
    if not shutil.which("systemctl"):
        return False
    r = subprocess.run(["systemctl", "cat", unit], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    return r.returncode == 0


def restart(mode: str, root: Path) -> str:
    """Restart ragline; returns the mode used ('systemd' | 'dev' | 'none')."""
    unit = os.environ.get("RAGLINE_SYSTEMD_UNIT", "ragline")
    if mode == "auto":
        mode = "systemd" if _systemd_unit_exists(unit) else "dev"
    if mode == "none":
        return mode
    if mode == "systemd":
        for argv in (["systemctl", "restart", unit], ["sudo", "-n", "systemctl", "restart", unit]):
            r = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if r.returncode == 0:
                return mode
        raise SystemExit(f"systemctl restart {unit} failed (as this user and via sudo -n)")
    if mode == "dev":
        script = root / "restart.sh"
        if not os.access(script, os.X_OK):
            raise SystemExit(f"{script} missing or not executable")
        log_dir = root / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = open(log_dir / "ragline-dev.log", "ab")          # noqa: SIM115 — handed to the child
        # Detached (own session) so it outlives this hook; restart.sh frees :8000
        # itself, then execs uvicorn.
        subprocess.Popen([str(script)], cwd=root, stdin=subprocess.DEVNULL, stdout=log,
                         stderr=subprocess.STDOUT, start_new_session=True)
        return mode
    raise SystemExit(f"RAGLINE_APPLY_RESTART={mode!r}: must be auto, systemd, dev or none")


def wait_healthy(url: str, timeout_s: float) -> str | None:
    """Poll /api/health until status == 'ok' (anonymous body is {"status": ...}).
    Returns the last status seen when it never got there (None = unreachable)."""
    deadline = time.time() + timeout_s
    last: str | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:      # loopback only by default
                body = json.loads(r.read().decode("utf-8"))
                last = str(body.get("status"))
                if last == "ok":
                    return "ok"
        except Exception:  # noqa: BLE001 — not up yet
            pass
        time.sleep(2)
    return last


def main(argv: list[str]) -> int:
    # -h/--help prints the module docstring (the full contract) and succeeds.
    if any(arg in ("-h", "--help") for arg in argv[1:]):
        print(__doc__)
        return 0
    if len(argv) != 2:
        print("usage: apply_pod_env.py <podlink client env file>", file=sys.stderr)
        return 1
    block_path = Path(argv[1]).expanduser()
    env_path = Path(os.environ.get("RAGLINE_ENV_FILE") or ROOT / ".env").expanduser()
    updates = parse_block(block_path.read_text(encoding="utf-8"))
    current = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    write_env(env_path, merge(current, updates))
    print(f"applied to {env_path}: {', '.join(sorted(updates))}")

    mode = restart(os.environ.get("RAGLINE_APPLY_RESTART", "auto").strip().lower() or "auto", ROOT)
    print(f"restart: {mode}")
    if mode == "none":
        return 0
    url = os.environ.get("RAGLINE_HEALTH_URL", "http://127.0.0.1:8000/api/health")
    timeout_s = float(os.environ.get("RAGLINE_HEALTH_TIMEOUT_S", "120"))
    status = wait_healthy(url, timeout_s)
    if status == "ok":
        print("ragline healthy: ok")
        return 0
    print(f"ragline not healthy after {int(timeout_s)}s (last status: {status})", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
