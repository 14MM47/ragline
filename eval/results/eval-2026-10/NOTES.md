# eval-2026-10 — campaign notes and deviations

Running log of facts the final report needs that the result files do not hold:
deviations from the plan, environment events, and measurements taken by hand.
Newest entries at the bottom of each rung.

**GPU memory is captured by hand** (decision 2026-10-14; RunPod's API reports
memory bandwidth, not memory in use). For every pod session, once the pod is
ready and questions are running, read the VRAM gauge on the pod's Telemetry tab
in the RunPod console ("N GiB / 96 GiB") and record it under the rung below with
the time and what was running. Rung 3 takes two readings (separate Instruct and
Thinking pod sessions). Pod-side `nvidia-smi` replaces this in Phase 3.

## Index build (r0-index), 2026-10-13/14

See `docs/eval/index-eval-2026-10-v1.md` and the build log in
`docs/eval/phase0-index-plan.md` §6. Total $9.73.

## Rung r2 — RedHatAI/Qwen3.8-27B-INT4, 2026-10-14

- **GPU placement deviation.** The weights volume's data centre (volume
  `<volume-id>`, EU-RO-1) returned a non-retryable create error on 2026-10-14
  and its stock probe answers "unknown". The rung 2 profile was changed to try
  any Secure-Cloud RTX PRO 6000 first (volume DC second); the original profile
  is in `~/.config/podlink/backup/`. Effect: weights download at boot instead of
  loading from the volume; same GPU model, so results are unaffected; boot time
  includes the download.
- **Boot time** (podlink event log, pod `<pod-id>`):

  | Step | Time | Elapsed |
  |---|---|---|
  | POD UP requested | 11:03:20 | 0:00 |
  | Pod created (stock on first attempt) | 11:03:24 | 0:04 |
  | Container running, access path open | 11:06:22 | 3:02 |
  | Embedder healthy | 11:10:50 | 7:30 |
  | Reranker healthy | 11:12:34 | 9:14 |
  | LLM healthy (all services) | 11:16:24 | 13:04 |
  | Stack test passed (reranker cold call 27 s) | 11:16:54 | 13:34 |
  | Client env handed to ragline | 11:17:08 | **13:48** |

- **GPU memory — configured budgets only; actual use NOT measured.** Neither
  podlink nor the pod image reads GPU memory, and the RunPod SDK's pod query
  does not return it (see `docs/eval/boot-vram-capture-plan.md`).
  Budgets on the 96 GB card from the profile: LLM (vLLM) 30 GB
  (`PODLINK_LLM_MEMORY_GB`, preallocated by vLLM, so actual ≈ budget),
  reranker (vLLM) 2.9 GB (`PODLINK_RERANK_MEMORY_GB`, preallocated), embedder
  (TEI, Qwen3-Embedding-8B, no budget: ≈ 16 GB weights plus activations,
  grows with batch size). **Allocated ≈ 49 GB of 96 GB**, ≈ 47 GB headroom.
  A reading from the RunPod console's GPU-memory gauge during the run, if
  taken, is recorded below.
- **GPU memory — measured by hand** (RunPod console, Telemetry tab, pod
  `<pod-id>`, uptime 1 h 31 min ≈ 12:34, during the thinking-OFF
  throughput probe): **VRAM 48 GiB of 96 GiB (51%)**, matching the configured
  ≈ 49 GB. GPU utilisation 0% at that instant (between probe requests),
  39 °C, 143 W of a 600 W limit, P-state P0. Driver 595.91.07, CUDA 13.2.
  Host: AMD EPYC 9335, system RAM 22.95 of 263.6 GiB in use, container disk
  177 MB of 55 GB. A single reading, not a peak over the run.
- **Throughput probe, thinking OFF** (24-question subset, end to end):
  1 stream 4.69 q/min, median 10.0 s; 4 streams 6.94 q/min, median 28.6 s —
  the pod saturates early (×1.5 throughput for ×4 concurrency).
- **RunPod API cannot supply GPU memory** (checked 2026-10-14 against this
  pod): its `memoryUtilPercent` / `memoryUtilization` is memory-bandwidth
  utilisation (88 → 11 → 88 % in step with GPU load), not occupancy. See
  `docs/eval/boot-vram-capture-plan.md`. Until a pod-side reading exists,
  VRAM per rung is a manual reading of the RunPod console gauge.
- **Pod stopped by RunPod at 13:47 (low account balance).** `lastStatusChange`:
  "Exited by Runpod: 2026-10-14 12:47 UTC"; balance $9.92 at the time (user
  topped up). Valid data kept: thinking OFF r1–r3 + OFF probe. The single
  finished ON pass moved to `r2/aborted-2026-10-14/on/r1.json`; ON pass 2 had
  24+ 404 errors and was never written. Session ledgered at $6.97. Runner
  stopped with SIGINT so its cleanup terminated the pod and restored .env.
- **Second pod session (ON + shakedown), started 13:57** with
  `--conditions on,off-rag` (new runner option): pod `<pod-id>`, ready
  14:13, **boot 947 s** (first boot recorded by podlink's own timeline).
- **GPU memory — measured by hand, session 2** (RunPod console, Telemetry,
  uptime 17 min 21 s ≈ 14:15, thinking-ON warm-up just starting):
  **VRAM 47 GiB of 96 GiB (49%)**; GPU 0% at that instant, 34 °C, 87 W;
  driver 595.91.07, CUDA 13.2. Host: **Intel Xeon 6960P**, system RAM 9.3 of
  175.1 GiB — a different host CPU from session 1 (AMD EPYC 9335). Same GPU
  model and driver; OFF and ON latencies come from different hosts, which the
  report notes as a threat to the OFF/ON latency comparison (answer quality
  is unaffected).
- **Thinking-ON run 2 stopped (15:22) — the ON setup was broken, not the model.**
  10 of 100 ON answers were EMPTY: vLLM counts reasoning inside `max_tokens`
  and the 5,500 ceiling ran out before the answer (those 10 were exactly the
  OFF→ON source-hit losses). Thinking was also on for every side call (query
  pre-pass 5.2 s/question, the 600-token library answer truncated), and
  reasoning was not being counted (current vLLM returns it as `reasoning`,
  ragline read `reasoning_content`). Files moved to
  `r2/aborted-2026-10-14/{on-run2,off-rag-run2}`. The runner was NOT
  interrupted (the signal went to its shell wrapper, twice); it ran on against
  the terminated pod and wrote a $0 ledger line, merged into the hand entry.
- **Redesigned ON condition (user-approved 2026-10-14):** thinking for ANSWERS
  ONLY (new `ANSWER_EXTRA_BODY`, applied to the RAG and library answer calls;
  pre-pass, confidence and memory keep thinking off as in OFF), answer and
  library ceilings 16,384, reasoning counted from either field name. OFF
  requests unchanged, so the three OFF passes stand. Runner: checks the pod
  is still ready before every pass and probe (aborts with cleanup if not),
  SIGTERM runs the same cleanup as SIGINT, prints its own pid.
- Rung 3's ON checkpoint (Thinking-2507) has no switch and thinks on every
  call; recorded as a known difference from the other rungs' ON.
- **Thinking-ON redo (run 3), started 15:41:** pod `<pod-id>` (as read
  from the console), ready 15:59, **boot 1,072 s** (podlink timeline).
- **GPU memory — measured by hand, run 3** (RunPod console, uptime 21 min 28 s
  ≈ 16:02, thinking-ON pass 1 running): **VRAM 48 GiB of 96 GiB (50%)**, GPU
  100%, 54 °C, 356 W of 600 W. Host **AMD EPYC 9554**, system RAM 23.35 of
  175.1 GiB. **Driver 580.173.02, CUDA 13.0** — older than the two earlier
  rung 2 sessions (595.91.07 / CUDA 13.2). Same GPU model; the third host of
  the day. Driver/host differences are recorded per session for the report's
  threats-to-validity section (latency comparisons across sessions).
- **Run 3 stopped by the user at 17:14** (end of session), during ON pass 1 at
  96 of 100 answered: no results file (written only at pass end); the 96
  answers survive as rows in `data/ragline_eval_v1.db` querytrace (created_at
  15:00–15:53 UTC). Session $3.88, ledgered by the runner's own cleanup
  (interrupted by its printed pid — worked as designed).
- **Fix confirmed:** reasoning is now recorded (2,500–27,700 reasoning chars
  per answer); no answer hit the 16,384 ceiling in pass 1 so far; ~32 s per
  question.
- **New blocker found:** ragline's OpenAI client sets no timeout, so the SDK
  default (600 s) applies. An answer that reasons towards the 16,384-token
  ceiling takes longer than 600 s at this model's decode speed, times out and
  is RETRIED FROM SCRATCH (SDK retries + tenacity 3 attempts) — question 97
  ran 20+ min at 100 % GPU. Before the next ON run: set an explicit, longer
  request timeout for answer calls and no blind retry of a timed-out
  generation (a timeout should be recorded as a truncated/failed answer, not
  regenerated), and/or lower the ON ceiling. Needs a decision.
- **Correction (2026-10-15) to the "new blocker" above.** Measured decode is
  ≈ 77 tok/s on the longest ON answers (8,956 completion tokens in 117 s), so
  even a full 16,384-token answer takes ≈ 3.5 min — inside the SDK's 600 s
  timeout; the answer call cannot have timed out. The likelier cause of the
  20-minute stall: calls with NO output ceiling — the JSON-mode query pre-pass
  (the only uncapped call on the eval chat path) can degenerate (endless
  whitespace/repetition is a known vLLM JSON-mode failure) and run to the
  65,536-token context, ≈ 14 min at 77 tok/s, at 100 % GPU. Unproven (the
  stuck question left no trace). Proposed fix: output ceilings on the
  pre-pass, memory and confidence calls, plus a slow-call warning naming the
  call; no timeout change needed. ON answers in run 3: completion tokens
  p50 838, p95 5,864, max 8,956 (none near 16,384).
- **Fix implemented 2026-10-15 (user-approved):** output ceilings on the
  chat side calls — `PREPASS_MAX_TOKENS`, `POST_PASS_MAX_TOKENS`,
  `CONFIDENCE_MAX_TOKENS`, 1,024 each (normal output a few hundred tokens);
  JSON mode now takes a ceiling and logs a cut-off reply; any call slower than
  `LLM_SLOW_CALL_S` (120 s) is logged with its purpose (prepass, answer,
  library_answer, memory, confidence), seconds and tokens. Thinking ON for
  rung 2 must be run in full (3 passes + probe + shakedown): run 3's pass 1
  never produced a results file. OFF passes stand (their side-call outputs
  were far below 1,024).
- **ON sampling changed 2026-10-15 (user-approved):** Qwen's thinking-mode
  guidance is temperature 0.6, top_p 0.95, top_k 20, min_p 0 and "DO NOT use
  greedy decoding" (degradation, endless repetition) — all earlier ON
  attempts ran greedy (temperature 0), which likely contributed to the
  runaway reasoning. New `ANSWER_TEMPERATURE` setting (answer calls only);
  ON = 0.6 + top_p/top_k/min_p in ANSWER_EXTRA_BODY; OFF stays greedy.
  Report states the asymmetry (each mode as the vendor intends); ON varies
  between passes, covered by the 3 repeats and bootstrap CIs. Per-model
  thinking sampling to be checked on each model card before its rung.
- **Run 4 (vendor sampling) interrupted 2026-10-15 ~10:07** — the Claude
  session closed by accident, killing the runner and the podlink console
  minutes after the pod was ready (09:53 create, ready 10:04, boot 600 s,
  1 ON question answered). Pod `<pod-id>` was found terminated and the
  account spend at $0/h, so the runner's SIGTERM handler most likely sent POD
  DOWN before the process was killed; the ledger line and .env restore did
  not happen and were done by hand (≈ $0.58 estimated). RunPod balance after:
  $11.54 — too low for a ~$10 rung (RunPod stopped a pod at ≈ $10 on
  2026-10-14); top-up needed before the rerun.

## Archive

- **Eval index archived 2026-10-15 15:28** to
  `%USERPROFILE%\Documents\ragline-eval-archive\index-ragline_eval_v1-2026-10-15\`
  (`scripts/eval_archive.py index`): Qdrant snapshot 313,098,240 bytes
  (sha256 d70d5258…7d57ea) and SQLite DB 7,277,760,512 bytes (sha256
  d59db147…7fa7f5b), with `digest.json`. Transcripts are archived to the same
  root after every rung from rung 3 on (rung 2 predates transcript capture).

## r2-s1 — stage 1 verification (2026-10-15)

- Same model/profile as r2 on the stage 1 query-time fixes (`97ccfa8`), index v1,
  50-question subset `eval/campaign/verify-stage1.ids` (35 diagnosed faults + 15 controls),
  3 passes OFF + 3 ON, chat path, no throughput probe.
- **GPU memory — measured by hand** (RunPod console Telemetry, pod `<pod-id>`,
  uptime 17m 14s, during OFF pass 1): **VRAM 49 GiB of 96 GiB (51%)** — same as r2's
  48 GiB within gauge rounding. Host AMD EPYC 9355, driver 595.91.07 / CUDA 13.2,
  RTX PRO 6000 Blackwell Server Edition, power limit 600 W.
- **Paused 2026-10-15 17:25 (user request, end of session):** thinking-OFF complete — 3 passes
  of the 50 questions in `r2-s1/off/r1-r3.json` with transcripts, not yet judged. Thinking-ON
  pass 1 was interrupted at question 2 of 50 (nothing saved for ON). Runner stopped by pid
  (SIGINT): pod terminated, `.env` restored, ledger entry written ($2.21, 0.89 h, boot 628 s;
  the entry lists both conditions but only OFF ran). Resume with
  `--rung r2-s1 --conditions on --skip-load --ids-file eval/campaign/verify-stage1.ids`,
  then judge both conditions.
