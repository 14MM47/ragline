# Plan — capture boot time and GPU memory per pod session

Status: APPROVED 2026-10-14. Boot time implemented (steps 3–6 for boot). GPU memory: RunPod's API cannot supply it (step 1), so it is captured MANUALLY per rung (user decision 2026-10-14); pod-side reading deferred to Phase 3. Medium (podlink + ragline runner +
report). Wanted before rung 3, because both measurements are lost once a pod
is terminated.

## Why

The plan's metrics (§5) include boot time to all-healthy and VRAM used; both
feed the 24 / 48 / 96 GB fit claims and the Phase 3 GPU table. Today:

- **Boot time** exists only as podlink's in-memory event log (lost on a console
  restart); the runner waits for readiness but records nothing. Rung 2's was
  reconstructed by hand into `eval/results/eval-2026-10/NOTES.md` (13 min 48 s).
- **GPU memory** is not read anywhere: not by podlink, not by the pod image,
  and the RunPod SDK's pod query (`runpod/api/queries/pods.py`) does not ask
  for it. Rung 2 has configured budgets only (≈ 49 of 96 GB).

## Options for GPU memory

| | A. RunPod API (recommended now) | B. Pod-side `nvidia-smi` |
|---|---|---|
| Where | podlink console asks RunPod's GraphQL for the pod's `runtime.gpus { memoryUtilPercent gpuUtilPercent }` | authproxy in the pod image serves `nvidia-smi --query-gpu=memory.used,memory.total` and `--query-compute-apps=pid,process_name,used_memory` |
| Precision | whole percent of the card (≈ 1 GB on 96 GB); total only | exact MiB, per process (LLM / embedder / reranker) |
| Stack change | none (console only) | **image rebuild** — changes the frozen stack mid-campaign |
| Risk | the field must exist in RunPod's schema — **unverified**, step 1 checks it. RunPod does track it: its console's Telemetry tab showed VRAM 48 GiB / 96 GiB (51%) for the rung 2 pod, so the data exists server-side | low technical risk; rebuild + boot check |

Recommendation: A for the rest of the ladder; B folded into the Phase 3 image
work (sm_89 / sm_90 boot checks need a new image anyway), where per-process
numbers matter most for the GPU table.

## Steps

1. **Verify the field** (podlink, no spend beyond the next rung's own pod): a
   one-off query of `pod(input:{podId}) { runtime { gpus { id memoryUtilPercent
   gpuUtilPercent } } }` against the next running pod. If RunPod's schema has no
   such field, stop here and report; option B becomes the only route.
2. **podlink provider** (`app/providers/runpod/provider.py`): `gpu_runtime(pod_id)`
   runs that query via the SDK's GraphQL helper and returns **only** the numeric
   fields (never `env`, ports or anything credential-bearing — same whitelist rule
   as `list_instances`). The card's memory in GB comes from the GPU type resolved
   at create (already known to the ladder).
3. **podlink status** (`app/driver.py`, `/status`): while RUNNING, refresh
   `gpu = {memory_util_pct, gpu_util_pct, card_memory_gb, memory_used_gb,
   memory_used_gb_peak}` at most every 30 s inside the existing poll; the peak
   resets per pod session. Add a structured `boot` dict alongside the event log:
   `{up_requested, created, running, services_healthy: {llm, embedder, reranker},
   stack_test_passed, client_env_written}` as epoch seconds, and `boot_s`.
4. **ragline runner** (`scripts/eval_campaign.py`): after readiness, copy `boot`
   and `boot_s` into the ledger entry and `--manifest-extra`; sample `/status.gpu`
   at the start and end of each condition and keep the session peak; write
   `vram_after_ready_gb`, `vram_peak_gb` and per-condition peaks to the ledger,
   the manifests and the rung SUMMARY.md. Absent fields (older console, failed
   query) are recorded as null, never fail a rung.
5. **Report** (`scripts/eval_report.py`): boot time and VRAM (after ready /
   peak / card) columns in the efficiency table; GPU-memory headroom in the
   per-tier recommendations; rung 2 taken from NOTES.md (budgets, marked
   "configured, not measured").
6. **Tests**: podlink — the query result is whitelisted (an `env` key in a fake
   response never reaches `/status`), percent → GB maths, peak reset per
   session, boot dict filled from a scripted start; ragline — FakeConsole carries
   `boot` and `gpu`, the runner writes them to ledger/manifest/summary, nulls when
   missing.
7. **Docs**: podlink README status-fields table; evaluation plan §5 metric
   definitions (VRAM = RunPod-reported card memory in use, whole-percent
   resolution; per-process split from Phase 3).

## Out of scope

Per-process memory and the image change (option B) — Phase 3. Back-filling
rung 2's actual memory: not possible after the pod is gone; a manual reading
from the RunPod console's GPU-memory gauge while the pod is still up is the
only way, and goes into NOTES.md if taken.

## Result of step 1 (2026-10-14, against the live rung 2 pod)

RunPod's API does **not** expose GPU memory in use. Both places it reports a
memory figure — `runtime.gpus.memoryUtilPercent` and
`latestTelemetry.averageGpuMetrics.memoryUtilization` — return the same
number, and it is **memory-controller (bandwidth) utilisation**, not
occupancy: sampled every 10 s it moved 88 → 11 → 88 % in lockstep with GPU
utilisation (100 → 14 → 100 %), while the console's VRAM gauge showed a steady
48 GiB / 96 GiB. Introspection is disabled on RunPod's GraphQL, and the
obvious field names (`memoryUsed`, `memoryUsedInMb`) do not exist. The
console's gauge comes from somewhere the public API does not reach.

So option A is out. Remaining routes:
- **B — pod-side `nvidia-smi`** via the authproxy: exact and per process, but
  needs an image rebuild (a stack change mid-campaign, or deferred to Phase 3).
- **Manual** — read the RunPod console's VRAM gauge once per rung during the
  run and record it in `eval/results/eval-2026-10/NOTES.md`, as done for
  rung 2 (48 / 96 GiB).
**Decision (user, 2026-10-14): manual capture for the rest of the campaign**;
the pod-side `nvidia-smi` reading is deferred to the Phase 3 image work.

## Boot time — what was built

- podlink: `PodSession.boot` (first time of each step: `up_requested`,
  `created`, `running`, `healthy_<service>`, `services_healthy`, `stack_test`,
  `client_env_written`, `ready`) and `boot_s` in `/status`; reset per POD UP,
  steps after `ready` ignored; closed on the recovery path too. Tests in
  `tests/test_session.py`, `tests/test_driver_smoke.py`; README.
- runner: `boot_record()` takes podlink's timeline, or its own wall-clock
  measure (POD UP request → ready) with an older console; written to the
  spend ledger (`boot`), every manifest (`boot_s`, `boot_source`) and a "Pod
  sessions" table in SUMMARY.md. Tests in `test_eval_campaign.py`.
- report: a "Boot s" column in the speed-and-cost table.
- The running console (rung 2) predates the podlink change, and rung 2's
  runner predates the runner change: rung 2's boot time (13 min 48 s) lives in
  NOTES.md. The new podlink code is live after the next console restart, which
  must not happen while a rung is running (the runner holds the console's
  token for POD DOWN).
