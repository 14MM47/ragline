# Phase 1 build plan — evaluation harness v2 and the gated campaign runner

Status: APPROVED 2026-10-13. Implements Phase 1 of
[evaluation-plan.md](../evaluation-plan.md) plus the per-rung protocol agreed the same day.
Tier: **Large** (new scripts, a shared-state change in the LLM provider, a new dev
dependency, drives a billed cloud resource). Pipeline: this plan → approval →
implement → `/alignment-verifier` → `/code-reviewer`; `/security-auditor` on the
podlink-driving script (it holds a console token and reads `.env`).

Nothing here changes the retrieval pipeline, prompts or ingestion. Every file keeps
the line-by-line comment standard.

## Progress

| Step | State | Commit |
|---|---|---|
| 1 Thinking switch and reasoning capture | done 2026-10-13 | 82aad56 |
| 2 evaluate.py v2 | done 2026-10-13 | d8fc910 |
| 3 eval_load.py throughput probe | done 2026-10-13 | this commit |
| 4 Human grades export | done 2026-10-13, mapping decided (C- partial, N wrong) | 82aad56 |
| 5 eval_judge.py | done 2026-10-13; prompts in eval/judge_prompts/ | this commit |
| 6 eval_campaign.py | done 2026-10-13: runner + eval/campaign/eval-2026-10.toml + 8 podlink profiles (ids verified on the model cards; all 8 pass `start.sh --check`); dry run of r2/r3 clean | this commit |
| 7 eval_report.py + figures | done 2026-10-13: matplotlib added to dev (dep-inspector: PSF/BSD, no CVEs; numpy already runtime); bootstrap/McNemar by hand; seven figures | this commit |
| 8 Calibration and shakedown | 8.1 done 2026-10-13: kappa 0.883 on the 2026-09-28 run (44/46; B11, D10 half-answered comparisons: human abstained, judge partial). 8.2 dry runs of r2 and r3 clean. 8.3 done 2026-10-13: /code-reviewer REQUEST_CHANGES (CRITICAL: pod up/wait outside the terminate block; HIGH: nDCG > 1 from duplicate chunks; MEDIUM: restore keys unvalidated, misnamed test; LOW: stage medians zero-filled) and /security-auditor (HIGH: unrestricted .env keys from the TOML, newline injection in merge; MEDIUM: LLM_EXTRA_BODY could shadow request parameters, campaign.log unredacted and committable, non-RunPod hosts published, condition values in manifests; LOW: ledger locking, podlink_dir path, no dead-man switch) — all fixed in the follow-up commit except the host-publishing policy (left for the user: the existing test documents recording non-RunPod hosts as they are) and the dead-man switch (podlink already has an auto-terminate countdown) | this commit |

## What exists and what is reused

| Thing | State | Reused as |
|---|---|---|
| `scripts/evaluate.py` | In-process runner: imports ragline, `agent.query()` per question, scores source-hit / cited / page sanity, records tokens, latency, `step_ms`, stack metadata | Core of v2; gains history replay, retrieval capture, repeats, thinking metadata |
| `ChatAgent.chat(session_id, question, use_memory, store)` | Chat path with `SessionMemory.turns` (`TurnRecord`) loaded from a `MemoryStore` | The `chat` path for follow-ups: seed a fresh session with the golden `history` turns, then ask |
| `RetrievalPipeline.retrieve()` | dense → BM25 → RRF `merged` → rerank → top-8 | Retrieval capture hooks on `merged` (top-20) and the rerank output |
| `TraceCollector` | prompt/completion tokens, `step_ms` | Gains `reasoning_chars` for thinking ON |
| `OpenAIProvider.complete()` | No `extra_body` | Gains a settings-driven `LLM_EXTRA_BODY` so thinking can be switched per condition |
| podlink console (`127.0.0.1:8765`) | `/config` (token), `/profiles`, `/profile/select`, `/pod/up`, `/pod/down`, `/status` with `services`, `test_result`, `client_env`, `cost_per_hr`, `session_cost_usd` | Driven over HTTP by the campaign runner; the runner never touches the secrets |
| `scripts/apply_pod_env.py` | Handoff hook: merges pod URLs + bearer into `.env`, restarts ragline | Unchanged; the runner waits for `client_env` to report success, then starts an in-process run that reads the fresh `.env` |
| `eval/results/2026-09-28_analysis.md` | 46 human grades as a markdown table (C / C- / A / N / W) | Converted once to `eval/human_grades_2026-09-28.json`; the judge calibration set |
| Claude Code headless (`claude -p --model claude-opus-5-5 --output-format json --json-schema … --tools "" --max-turns 1 --no-session-persistence`) | Verified 2026-10-13: structured output, Max login, 2.7 s/call | The judge transport |
| Codex bridge (`~/.claude/scripts/codex_bridge.sh`) | Exists | The GPT-5.x second-opinion transport |

## Deliverables (files)

```
scripts/evaluate.py            v2 (modified)
scripts/eval_judge.py          new
scripts/eval_load.py           new
scripts/eval_report.py         new
scripts/eval_campaign.py       new — one gated rung per invocation
scripts/eval_human_grades.py   new — one-off converter for the 2026-09-28 grades
src/ragline/config.py          + LLM_EXTRA_BODY (JSON string, default "")
src/ragline/llm/openai_provider.py   extra_body pass-through; reasoning_content length → trace
src/ragline/tracing/collector.py     + reasoning_chars
src/ragline/retrieval/pipeline.py    retrieval-capture hook (no behaviour change when unset)
eval/human_grades_2026-09-28.json    generated, user-confirmed
eval/campaign/eval-2026-10.toml      campaign definition: rungs, conditions, repeats, budget
tests/unit/test_eval_*.py            one test module per script
docs/evaluation.md                   harness v2 section
podlink: deploy/profiles/eval/*.conf.example (7 rungs + Phase 3 cards) and
         ~/.config/podlink/profiles/eval-*.conf (user's copies)
```

## Steps

Each step is independently reviewable; steps 1–4 are the harness, 5 the judge, 6 the
runner, 7 the report, 8 the calibration and shakedown. Dependencies are noted.

### 1. Thinking switch and reasoning capture (ragline core; Small)

1.1 `config.py`: add `llm_extra_body: str = ""` (env `LLM_EXTRA_BODY`), a JSON object
    merged into every chat-completion call as `extra_body`. Validated at startup
    (must parse to a dict or be empty). Strict `.env` rule: adding a setting is
    allowed; nothing is removed.
1.2 `openai_provider.py`: pass `extra_body` in `complete`, `complete_json` and the
    streaming call. Read `choices[0].message.reasoning_content` when present and add
    its length to the trace (`reasoning_chars`); never append it to the answer.
1.3 `collector.py`: `reasoning_chars` field, included in `finalize()`.
1.4 Harness assertion (step 2): if `<think>` or `</think>` appears in any answer the
    run is marked `think_residue=true` and the condition fails loudly.
1.5 Tests: provider passes `extra_body` only when set; `reasoning_content` goes to the
    trace, not the text; config rejects non-object JSON.

Thinking ON for the Qwen hybrid rungs = `LLM_EXTRA_BODY={"chat_template_kwargs":{"enable_thinking":true}}`
with the pod started with `--reasoning-parser qwen3`. Thinking OFF =
`{"chat_template_kwargs":{"enable_thinking":false}}`. As built (2026-10-13): the eval
profiles KEEP the `enable_thinking:false` template default, and both conditions set the
flag explicitly per request (a per-request kwarg overrides the default), so a warm-up
or a stray request can never think by accident. Reasoning budget: vLLM has no
model-independent reasoning cap, and it counts reasoning tokens inside `max_tokens`,
so the ON condition raises `ANSWER_MAX_TOKENS` to 5500 (4k reasoning + 1.5k answer)
and the report states that reasoning length is bounded only by that ceiling. Gemma 4
uses `--reasoning-parser gemma4`; the always-thinking Thinking-2507 checkpoint uses
`deepseek_r1`.

### 2. `scripts/evaluate.py` v2 (Medium)

2.1 Manifest (`run.meta`): everything v1 records plus `gpu` (name, count, VRAM),
    `rate_usd_per_hr`, `cloud`, `vllm_args`, `quantization`, `thinking` (off/on),
    `llm_extra_body`, `index_digest` (Qdrant collection name + point count + the
    ingestion manifest hash), `golden_digest`, `ragline_rev`, `repeat`, `seed`,
    `warmup`, `label`, `campaign`, `rung`. GPU/rate/vllm fields come from
    `--manifest-extra <json>` (the campaign runner fills them from podlink's status
    and the profile); run standalone they are null, never guessed.
2.2 `--path rag|chat` (default `rag`). `chat` creates a fresh in-memory
    `MemoryStore` session per question, pre-loads the golden `history` turns as
    `TurnRecord`s (user_query + answer, no spans), then calls `ChatAgent.chat()`.
    Questions without `history` still go through the chat path so the condition is
    uniform. `rag` keeps v1 behaviour and asks follow-ups cold, flagged
    `history_replayed=false`.
2.3 Retrieval capture: a `capture` callback on `RetrievalPipeline.retrieve()`
    (None by default = no change) receives `merged[:20]` and the reranked top-8.
    Per question the result records both lists as `(source_file, page, chunk_id,
    score)` and computes recall@20, recall@8, MRR, nDCG@8 against
    `expected_sources`/`expected_pages`, plus `page_hit` and `distractor_cited`
    (for entries with `distractor_evidence`).
2.4 `--repeats N` and `--warmup K`: K untimed questions (first K of the set) before
    repeat 1; each repeat is a separate results file `<run>_r<N>.json` with its own
    manifest; identical seed recorded (temperature is 0, so seed is documentary).
2.5 Unanswerables: `declined` detection (regex on the refusal phrasing + zero
    citations) recorded per answer so the judge has a prior.
2.6 Output layout: `eval/results/<campaign>/<rung>/<condition>/r<N>.json` when
    `--campaign` is set; the v1 flat layout otherwise. The existing `--threshold`
    and `--label` stay.
2.7 Tests: history seeding produces the expected `SessionMemory`; retrieval metrics
    on a synthetic candidate list (recall, MRR, nDCG by hand); manifest field
    presence; think-residue flag; repeats write N files.

### 3. `scripts/eval_load.py` — throughput probe (Small)

3.1 Fires the same 24 golden questions (a fixed, documented subset spanning
    categories) at concurrency 1, 4 and 8 through `agent.query()` with
    `asyncio.Semaphore`; records per-stream latency, TTFT (first token via the
    streaming call), decode tok/s (completion tokens / generation step time),
    aggregate questions/min, and errors.
3.2 Output `load.json` next to the run files, with the same manifest.
3.3 Test: concurrency bookkeeping on a fake agent with sleeps.

### 4. `scripts/eval_human_grades.py` (Trivial, one-off)

4.1 Parses the per-question table in `eval/results/2026-09-28_analysis.md`
    (ranges like `A02–A08 C ×7` expanded) into
    `eval/human_grades_2026-09-28.json`: `{id, grade, note}` mapped to the judge's
    scale (C, C- → correct; A → abstained; N → partial; W → wrong).
4.2 The user confirms the JSON (46 rows) before it is used for calibration.

### 5. `scripts/eval_judge.py` (Medium)

5.1 Input: one or more results files. Output: `<run>.judge.json` beside each, with
    per-answer `correctness` (correct / partial / wrong / abstained), `faithfulness`
    (claims list, each supported / unsupported by the retrieved chunks captured in
    2.3), `citation_support` (each cited source used / unused), and the judge's
    reason. Unanswerables: `declined` / `answered_wrong`.
5.2 Transport: `claude -p` headless with `--json-schema` for each of the three
    tasks, batched ~20 answers per call, prompts kept in `eval/judge_prompts/`
    (versioned, hashed into the output). Pinned `--model claude-opus-5-5`; the
    response's reported model id is stored. `--tools ""`, `--max-turns 1`,
    `--no-session-persistence`. Backoff on non-zero exit or throttling text,
    resumable: a run whose `.judge.json` exists and matches the prompt hash is
    skipped.
5.3 `--second-opinion`: a 20 % stratified sample (by category) plus every
    judge-vs-human disagreement is sent through the Codex bridge with the same
    prompt and schema; results stored as `judge2` fields; agreement (Cohen's κ)
    reported. Each Codex call is billed; the count is printed.
5.4 Calibration mode `--calibrate eval/human_grades_2026-09-28.json`: grades the
    2026-09-28 run, prints κ and the confusion matrix, exits non-zero below κ 0.8.
5.5 Tests: batching and resume logic with a fake `claude` executable on PATH;
    schema validation; κ computation on a known table.

### 6. `scripts/eval_campaign.py` — one gated rung per invocation (Medium; security review)

6.1 Reads `eval/campaign/eval-2026-10.toml`: campaign name, budget cap, stop-ask
    trigger, repeats, warmup, and per rung: `profile`, `model`, `conditions`
    (`off`, `on`, with the `LLM_EXTRA_BODY` for each and whether `on` needs its
    own profile), `expected_weights_gb`.
6.2 `--rung <name>` runs exactly the protocol from the plan:
    preflight (`start.sh --check --profile …` subprocess; ledger below trigger) →
    `POST /profile/select` → `POST /pod/up` → poll `/status` until `state=RUNNING`,
    all `services` healthy, `test_result` ok and `client_env` success →
    ragline health check → for each condition: write `LLM_EXTRA_BODY` to `.env`
    via the same merge routine `apply_pod_env.py` uses (no hand edits), run
    `evaluate.py` with warmup + repeats + manifest extras, run `eval_load.py` →
    `POST /pod/down` with `terminate=true` → read `session_cost_usd` and
    `cost_per_hr` → append `spend.jsonl` → run `eval_judge.py` and `eval_report.py
    --rung` → write `SUMMARY.md` for the rung → exit 0.
6.3 Safety: refuses to start if a pod is already running; refuses if the ledger is
    at or above the trigger; every pod-down failure is retried and then reported
    with the pod id in capitals so a stray pod is never silent; the console token is
    read from `/config` at start and never written anywhere; an optional
    `--notify` sends a push notification through Claude Code when the rung
    completes or fails.
6.4 `--dry-run`: everything except the pod and LLM calls (fake podlink responses),
    used in tests and for the shakedown before the first rung.
6.5 Tests: state machine against a fake console (httpx mock); ledger gate; terminate
    on every failure path.

### 7. `scripts/eval_report.py` and figures (Medium; dep-inspector)

7.1 New dev dependency: `matplotlib` (static SVG/PNG for the markdown report) and
    `numpy` (bootstrap). `/dep-inspector` first; both are permissive-licence,
    widely used. No plotly in the repo: the interactive page is produced from the
    report's JSON by the artifact step outside the repo.
7.2 Aggregation per run / condition / rung / card: correctness rate with 10k-sample
    paired bootstrap CIs, per-category breakdown, faithfulness rate, citation
    support rate, retrieval recall@20/@8, MRR, nDCG@8, latency median/p90, TTFT,
    decode tok/s, throughput at 1/4/8, tokens and reasoning chars, cost per 1,000
    questions (`rate × wall time / questions`), spend to date. McNemar for every
    rung vs the baseline rung and for ON vs OFF within a rung.
7.3 Outputs: `report.json` (everything), `figures/*.svg` (correctness by rung with
    CIs; correctness by category heatmap; ON vs OFF deltas; latency vs correctness
    scatter; cost per 1,000 Q; retrieval recall by category; Phase 3 cards: cost vs
    throughput), and `REPORT.md` assembled from a template with the tables and
    figure links. `--rung` emits the per-rung `SUMMARY.md` used at each gate.
7.4 Tests: bootstrap CI and McNemar on known inputs; report renders from two fake
    runs.

### 8. Calibration and shakedown (no new code)

8.1 Run `eval_judge.py --calibrate` on the 2026-09-28 results; iterate on the judge
    prompt until κ ≥ 0.8 against the 46 human grades; record the final κ.
8.2 `eval_campaign.py --dry-run --rung r2` end to end.
8.3 Exit criterion for Phase 1: tests green, `/code-reviewer` verdict APPROVE,
    `/security-auditor` on `eval_campaign.py` with no HIGH findings, κ recorded.
    Phase 2 rung 2 (the shakedown rung) is then the first spend.

## podlink profiles (written alongside step 6, user copies them into place)

`deploy/profiles/eval/eval-r1-qwen3-4b.conf.example` … `eval-r6-qwen3.5-122b.conf.example`
plus `eval-r3-thinking.conf.example` (the separate 2507 Thinking checkpoint) and, for
Phase 3, `eval-card-{h100,l40s,a6000,pro4500}.conf.example`. Each: PRO 6000 ladder
rung, volume <volume-id>, `PODLINK_LIFECYCLE=terminate`, `--reasoning-parser`,
`--max-num-seqs 8`, `--max-model-len 65536`, memory budget per the fit rule, same
embedder and reranker as prod, client-env handoff to ragline. Each is preflighted
with `start.sh --check` before its rung.

## Out of scope for Phase 1

Phase 0.3 defect fixes (own plan), the index rebuild (0.4), any retrieval or prompt
change, the interactive report page (Phase 5), the Phase 3 image boot checks.

## Order and effort

Steps 1 → 2 → 3 and 4 → 5 can proceed as two parallel tracks; 6 needs 2, 3, 5; 7 needs
2 and 5; 8 needs all. Roughly 3–4 working days including reviews.
