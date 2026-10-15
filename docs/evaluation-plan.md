# ragline full evaluation plan — models × GPUs on the golden set

Status: APPROVED 2026-10-13 (all §8 decisions taken; see §8). Owner: Matt. Phase 0.1/0.2
(golden set v1.0) completed 2026-10-13; Phase 1 harness completed 2026-10-13; Phase 0.3–0.5
(defect fixes, eval index, tag `eval-2026-10-v1`) completed 2026-10-14. Next: Phase 2 rung 2 shakedown.

## 1. Goal

Produce an industry-standard, reproducible comparison of ragline's answer quality,
latency and cost across (a) a ladder of generator LLMs from ~4B up to the largest that
fits on one RTX PRO 6000 (96 GB) alongside the embedder and reranker, and (b) a set of
GPUs for the configurations that fit them, all measured on the same frozen corpus
index and the same approved golden question set (target 100 questions). The output
is a written report with a leaderboard, per-category breakdowns, quality-vs-cost
frontier, error taxonomy, statistical confidence, and a deployment recommendation
per VRAM tier (24 / 48 / 96 GB).

## 2. What exists today (the starting point)

| Asset | State | Gap for this eval |
|---|---|---|
| `eval/golden_set_hmi.json` | 100 Q, 7 categories, all 100 hand-reviewed 2026-10-13 (digest a9c5b770795f) | None: v1.0 candidate, freeze at Phase 0.5 |
| `scripts/evaluate.py` | Runs the RAG path per question; records source-hit, cited, page sanity, latency, tokens, per-stage ms; run metadata | No correctness/faithfulness grading, no history replay, no retrieval metrics, single run only, no GPU/price/vLLM metadata |
| Hand grading | 46 answerable Q graded once (2026-09-28 analysis) | Becomes the judge calibration set |
| Index | Eval index `ragline_eval_v1` built 2026-10-14: 119 docs, 15,064 chunks, pymupdf4llm 1.28.2, table-aware chunker, KG by Qwen3-30B-A3B-2507-AWQ (docs/eval/index-eval-2026-10-v1.md) | None: frozen at tag `eval-2026-10-v1` (prod/dev index `ragline_pod` unchanged) |
| Pod stacks (podlink) | Profiles for PRO 6000, A6000, PRO 4500 ladder; image 2026-09d (sm_86 + sm_120); vLLM 0.25.1 | Per-model profiles for the ladder; H100/L40S rungs untested |
| Known pipeline defects | Chunk-level causes of D10 (decoy fragment) and A09 (mid-row table split) fixed in the chunker; both still fail on retrieval ranking; comparison Qs retrieve one side; graph index rebuilt per query | Retrieval-side, kept out of the freeze (Phase 4) |
| Noise floor | 42–45/51 across 4 runs of the same stack; only 30/60 answers byte-identical between same-day runs | Repeats + paired statistics are mandatory |

## 3. Design principles

1. **One variable at a time.** Freeze the corpus, parser version, chunking, embedder,
   reranker, KG extraction, prompts, ragline revision and golden set. The LLM ladder
   changes only the query-time generator. The GPU axis changes only the card.
2. **Grade answers, not just citations.** Source hit-rate overstated quality by ~13%
   in the first run. Correctness and faithfulness are graded by an LLM judge that is
   calibrated against the existing human grades, with human adjudication of every
   disagreement in the final leaderboard.
3. **Measure the noise before claiming a difference.** Every configuration runs ≥3
   times; comparisons are paired per question with bootstrap confidence intervals
   and McNemar's test against the baseline. A difference inside the CI is reported
   as "no difference".
4. **Separate retrieval from generation.** Retrieval metrics (recall@k, MRR, page hit)
   are identical across the LLM ladder by construction, which is itself a check that
   the freeze held; generation metrics are what the ladder measures.
5. **Cost is a first-class metric.** Every run records GPU type, on-demand £/$ rate,
   wall time, so the report can give cost per 1,000 questions and a quality-vs-cost
   frontier, not just a quality ranking.
6. **Reproducible by a stranger.** Each run has a manifest (models, quant, vLLM
   version + args, image tag, GPU, driver, ragline rev, golden-set digest, index
   digest). The report ships with the raw results JSON and the aggregation script.

## 4. Phases

### Phase 0 — Freeze the yardstick (blocks everything else)

0.1 **Golden set v1.0 (user-owned) — DONE 2026-10-13.** All 100 entries reviewed by
    hand against the PDFs; A01 / D02 / C11 confirmed correct; one discrepancy found
    (A06: the installation instructions also carry a UK UKEX sibling certificate,
    UL21UKEX2323X) and the expected answer amended to name it as a wrong substitute.

0.2 **Expand to 100 questions** — DONE (drafted 2026-10-12, reviewed 2026-10-13; digest
    a9c5b770795f, 181 evidence quotes machine-checked against page text, 93 of 119
    documents cited).
    Distribution, chosen so every category has enough items to report a per-category
    number with a usable CI:

| Category | Now | Target | Notes |
|---|---:|---:|---|
| spec (single fact, single doc) | 36 → 48 | 48 | Add numeric-table cases deliberately (the known failure mode), units/ranges, footnote-qualified values |
| comparison (two products, two docs, `all`) | 10 → 18 | 18 | Both sides must be cited; include same-vendor and cross-vendor pairs |
| multihop / aggregation (new, ids G) | 0 → 8 | 8 | "Which of these three panels supports X?", "list models rated IP66" — needs ≥2 chunks |
| procedure / how-to (new, ids H) | 0 → 8 | 8 | Steps from a manual; graded on completeness and order |
| unanswerable | 6 → 10 | 10 | Mix of near-miss (sibling model exists) and absent topics; score false-answer rate |
| followup (with `history`) | 5 | 5 | Keep; harness gains history replay (1.2) |
| library | 3 | 3 | Keep; run through the chat path (1.2); scored separately |

    Rules for new entries: every entry carries `evidence` with a verbatim quote and
    page, a `source_match` rule, a `difficulty` tag (easy/table/long-doc/distractor),
    and a `review_note`; drafted from the PDFs, verified by hand before v1.0.
    Decision for the user: stay HMI-only (recommended: one deep, hand-verified corpus
    is the stronger comparison) vs. mix in the 50-question all-categories draft
    (would require ingesting ~700 more docs and verifying 50 more answers).

0.3 **Pipeline defect triage.** Decide which of the known defects to fix before the
    freeze. Recommendation: fix ingestion-content defects (empty chunk D10, blank
    table row A09) because they cap every model identically and hide model
    differences; leave retrieval-strategy changes (per-entity split for comparisons,
    graph index cache) out of the freeze and evaluate them later as their own axis.
    Any fix goes through the normal plan → review pipeline first.

0.4 **Rebuild the index once, on pymupdf4llm 1.28.2**, into a fresh Qdrant collection
    + SQLite DB + storage dir named for the eval (e.g. `ragline_eval_v1`), with
    `Qwen/Qwen3-Embedding-8B` (4096-d, with the query instruction setting as it will
    be used in the runs) and KG extraction by ONE fixed model (the prod
    `Qwen3-30B-A3B-2507-AWQ`, extraction concurrency as per profile). Record a digest
    of the index (doc count, chunk count, entity count, parser version) in the
    manifest. The same index serves every LLM-ladder and GPU-axis run; the LLM
    ladder never re-ingests.

0.5 **Tag the ragline revision** used for all runs (`eval-2026-10-v1`), after the
    harness work in Phase 1 lands. Prompts, top-k, chunking are part of the tag.

Exit criteria: golden set v1.0 digest recorded; index built and smoke-tested; baseline
run of the prod stack on PRO 6000 passes with no errors.

### Phase 1 — Harness upgrade (`scripts/evaluate.py` v2 + helpers; Medium task)

Each item is a plan → implement → review unit on its own branch.

1.1 **Run manifest** adds: GPU name/count/VRAM, cloud + on-demand rate (from podlink
    profile or `--gpu-rate`), vLLM version + full args, image tag, quantisation,
    `max_model_len`, `max_num_seqs`, thinking on/off, index digest, repeat number,
    random seed, harness version.

1.2 **Chat-path mode and history replay.** `--path rag|chat`: `chat` drives
    `ChatAgent` (pre-pass, intent routing, library listing) so followup and library
    questions are measured for real; `history` is replayed as the previous turn in a
    fresh session per question.

1.3 **Retrieval capture.** Record the top-20 hybrid candidates and the top-8 after
    rerank (doc, page, chunk id, score) per question. Compute recall@20, recall@8,
    MRR, nDCG@8 on `expected_sources`; page-level hit on `expected_pages`;
    distractor-cited flag on `distractor_sources`.

1.4 **Judge module** (`scripts/eval_judge.py`, separate from the run so it can be
    re-run offline). Per answer, three structured calls to a frontier judge model:
    (a) correctness vs `expected_answer` + `evidence` → correct / partial / wrong /
    abstained; (b) faithfulness: list the answer's factual claims and mark each
    supported / unsupported by the retrieved chunks; (c) citation support: is each
    cited source actually used. Unanswerables are scored as declined / answered-wrong.
    Judge prompt, model id and version are recorded. Position bias is irrelevant
    (single-answer grading); verbosity bias is countered by grading against evidence
    rather than against the expected text alone.

1.5 **Repeats and seeds.** `--repeats N` runs the set N times in one job with a
    fresh pod-side prefix-cache state where possible; results files carry
    `repeat` so aggregation can compute per-question agreement across repeats.

1.6 **Throughput probe** (`scripts/eval_load.py`): fires 1 / 4 / 8 concurrent golden
    questions through the HTTP API for a fixed window; reports tokens/s aggregate,
    p50/p95 latency, TTFT (streaming), and errors. Requires `max_num_seqs ≥ 8` in the
    profile under test — recorded in the manifest.

1.7 **Aggregation + comparison** (`scripts/eval_report.py`): reads a directory of
    results, joins judge outputs, produces per-config and per-category tables,
    paired per-question deltas vs a named baseline, bootstrap 95% CIs (10k resamples)
    on correctness and hit-rate, McNemar's exact test, cost per 1,000 questions,
    and writes Markdown + CSV. Deterministic, unit-tested on fixture data.

1.8 **Judge calibration run.** Grade the 2026-09-28 and 2026-09-29 results with the
    judge; compare against the 46 human grades; target Cohen's κ ≥ 0.8 on the
    4-way label. Iterate the judge prompt until met; record final κ in the report.
    Human adjudicates every judge/human disagreement and the adjudicated label wins.

Exit criteria: all new scripts unit-tested, `/code-reviewer` pass, κ target met,
dry run of the full flow on the baseline stack.

### Phase 2 — LLM ladder on the fixed GPU (RTX PRO 6000, 96 GB)

Fixed: index from 0.4, embedder Qwen3-Embedding-8B on TEI (~16 GB), reranker
Qwen3-Reranker-0.6B on vLLM (~3 GB) — identical to the recorded runs, so the
reranker is NOT a variable here. Fit rule for a rung: weights + KV at 64k ctx +
19 GB (embed+rerank) + ~5 GB headroom ≤ 96 GB. `max_model_len` 65536,
`max_num_seqs` 8 (so the throughput probe is meaningful), temperature 0.

**Five active rungs (2, 3, 4, 5, 6) since 2026-10-14.** The user cut the ladder from
seven to five: rungs 1 (4B) and 1b (8B) are **deferred, not deleted** — their rows,
campaign entries (`deferred = true`) and podlink profiles are kept so the full
4B → 122B ladder can be resumed with `--include-deferred`. The active set keeps the
rungs that inform a decision: the 24 GB baseline (2), the prod model and the two
replacement candidates (3–5, the pending 3-way A/B) and the 96 GB ceiling (6); the
spread is 26B → 122B. Cost of the cut: the report cannot say how small a generator
can go.

The original seven rungs (six plus Qwen3-8B, added 2026-10-13 for a cleaner single-family size
curve) were chosen for a full parameter spread (4B → 122B) while keeping the
recorded baseline, the deployed prod model and the two replacement candidates
from the 2026-09 research pass. **Every rung is run in two conditions, thinking
OFF and thinking ON**, so the report can say per size class whether reasoning
fixes the table-misread errors and what it costs in latency and tokens.

| Rung | Model (HF id) | Weights | Fits 24 / 48 / 96 | Thinking ON = | Why it is on the ladder |
|---|---|---:|---|---|---|
| 1 *(deferred)* | `Qwen/Qwen3-4B` (FP8 build) | ~4 GB | ✓ / ✓ / ✓ | `enable_thinking: true` (hybrid) | Floor of the spread; smallest credible generator |
| 1b *(deferred)* | `Qwen/Qwen3-8B` (FP8 build) | ~8 GB | ✓ / ✓ / ✓ | `enable_thinking: true` (hybrid) | Second small-dense point so the 4B→27B gap has a datapoint; same family and template as rung 1 |
| 2 | `RedHatAI/Qwen3.8-27B-INT4` | ~17 GB | ✓ / ✓ / ✓ | `enable_thinking: true` | The recorded 3090-stack baseline (4 runs exist); the 24 GB tier |
| 3 | `stelterlab/Qwen3-30B-A3B-Instruct-2507-AWQ` | ~18 GB | ✓ / ✓ / ✓ | sibling checkpoint `Qwen3-30B-A3B-Thinking-2507` (AWQ) — Qwen shipped the 2507 pair as separate weights, so the ON condition is a different checkpoint and the report says so | Deployed prod generator; fast MoE |
| 4 | `Qwen/Qwen3.6-35B-A3B-FP8` | ~37 GB | ✗ / ✓ / ✓ | `enable_thinking: true` | Candidate replacement (speed, 262k ctx); faithfulness unproven |
| 5 | `google/gemma-4-26B-A4B-it` (FP8) | ~27 GB | ✗ / ✓ / ✓ | its thinking switch if the chat template exposes one; otherwise OFF-only and marked as such | Best measured HHEM of the fit set (5.2%); grounding-first candidate |
| 6 | `Qwen/Qwen3.5-122B-A10B-GPTQ-Int4` | ~65 GB | ✗ / ✗ / ✓ | `enable_thinking: true` | Largest model that fits with embed+rerank; profile already exists (agentic) |

The 26–37B band is deliberately crowded: it is the 48 GB deployment tier where the
buy/rent decision sits, and rungs 3–5 are the pending 3-way A/B. There is no
thinking-capable open 70B-class model that fits beside the retrieval services at
64k context, so the spread jumps from 37 GB to 65 GB of weights; gpt-oss-120b
(reasoning levels, ~63 GB, HHEM 14%) is the one alternative for rung 6 if the
122B fails to load, not an extra rung.

Thinking-ON protocol: vLLM started with the model's reasoning parser so thinking
text never reaches ragline's answer or citation extraction (harness check in
Phase 1: assert no `<think>` residue in answers); thinking budget capped
(`answer_max_tokens` unchanged, reasoning tokens capped at 4k and recorded
separately); latency, completion tokens and reasoning tokens reported per
condition; a `thinking` field in the manifest.

Per-rung run protocol (agreed 2026-10-13; executed by `scripts/eval_campaign.py`,
one rung per invocation, gated):

1. Preflight the rung's podlink profile (`start.sh --check --profile eval-<rung>`,
   spends nothing); refuse to start if the spend ledger is at or above the $250
   trigger. No image build per rung: every Phase 2 rung runs on the PRO 6000, which
   image 2026-09d already covers (image work is Phase 3 only, for L40S/H100).
2. Pod up. "Fully up" = all three services healthy AND podlink's stack test passed AND
   the client-env handoff written and ragline restarted AND ragline's health endpoint
   answering. Then a few untimed warm-up questions so cold caches stay out of repeat 1.
3. Thinking OFF: 3 full repeats of the 100 questions, then the throughput probe at
   1 / 4 / 8 streams.
4. Thinking ON: same, with the no-residue assertion on every answer. For the Qwen
   hybrid rungs this is a per-request template switch on the same pod (reasoning
   parser enabled at vLLM start for both conditions). Rung 3 (different checkpoint)
   and Gemma if its template has no switch need a second pod session instead.
5. Pod down — terminate, not stop (a stopped pod bills its disk; weights live on the
   network volume). Read the session cost from podlink's status snapshot and append
   it to `eval/results/<campaign>/spend.jsonl`.
6. Offline, no GPU: retrieval metrics, Opus 5.5 grading of all 600 answers via Claude
   Code headless, bootstrap CIs, and a rung summary written to the results directory.
7. Stop. The summary and the running total are reported (optionally as a push
   notification); the next rung starts only on an explicit OK.

GPU memory (manual, decided 2026-10-14): RunPod's API reports memory bandwidth, not
memory in use, so once per pod session, after the pod is ready and while questions
are running, the user reads the VRAM gauge on the pod's Telemetry tab in the RunPod
console ("N GiB / 96 GiB") and the reading is recorded under that rung in
`eval/results/eval-2026-10/NOTES.md` with the time and what was running. Claude
prompts for it when each pod becomes ready. Rung 3 needs two readings (Instruct and
Thinking checkpoints run in separate pod sessions). A pod-side `nvidia-smi` reading
(exact, per process) replaces this in the Phase 3 image work.

Order: rung 2 (the 27B baseline with four recorded runs) goes FIRST as the shakedown
of the new harness — it must reproduce the known 42–45/51 source-hit range before any
other rung is spent on — then the rest in size order (3, 4, 5, 6; 1 and 1b deferred). Judge
calibration (Phase 1.8) is done before rung 2 so every gate report carries trusted
grades. Expect ≈ 2–3 h pod time (≈ $5–6) plus ~1 h offline grading per rung.

Rules: a rung that fails to load after the documented fallback (bf16 KV →
enforce-eager) is reported as "did not fit" with the error, not silently
dropped. Exact HF ids and sizes are confirmed on each model card before the
profile is written; NVFP4 MoE checkpoints are excluded on sm_120 (known-flaky
kernels). If Qwen4-27B open weights land during the eval, it is added as an
addendum rung with the same protocol, not retro-fitted into the frozen ladder.

Per rung: 2 conditions × 3 full repeats of the 100-question set (≈ 13 min per
OFF repeat on PRO 6000 at the observed 7.6 min/60 Q; ON repeats take longer),
1 throughput probe per condition, judge pass. ≈ 2–2.5 GPU-hours per rung
including model load; 5 active rungs ≈ 18–20 GPU-hours at the pace measured on rung 2 (≈ 4 h/rung incl. the shakedown pass); the deferred 1 and 1b would add ≈ 6–7 h.

### Phase 3 — GPU axis (fixed models, several cards)

Models: rung 2 (Qwen3.8-27B-INT4, fits everything, 4 recorded runs already) and the Phase 2 quality winner
that fits 48 GB. Each card runs both where they fit, 3 repeats + throughput probe.

| Card | VRAM / arch | On-demand (RunPod Secure, Sep-2026 refs, verify live) | Role |
|---|---|---|---|
| RTX PRO 6000 Blackwell | 96 GB sm_120 | ~$1.99–2.09/h | Reference; all Phase 2 numbers |
| H100 80 GB (PCIe or SXM) | 80 GB sm_90 | ~$2.89–2.99/h | Datacenter reference; FP8 native |
| L40S | 48 GB sm_89 | ~$0.99–1.19/h | 48 GB Ada with FP8 |
| RTX A6000 | 48 GB sm_86 | ~$0.53/h | 48 GB Ampere (one run recorded); no FP8 |
| RTX PRO 4500 Blackwell | 32 GB sm_120 | ~$0.72/h | The buy-target proxy (ladder exists) |

Measured per card: correctness (expect equal within CI — a check, not a result),
median/p90 latency, decode tok/s, TTFT, throughput at 1/4/8 streams, boot time to
all-healthy, cost per 1,000 questions, and VRAM headroom. The podlink memory-budget
knobs (`PODLINK_LLM_MEMORY_GB`, `_KV_GB`) are used only to confirm fit, never for
speed numbers — speed is measured on the real card only. Image 2026-09d covers
sm_86 and sm_120; sm_89/sm_90 need a boot check first (TEI router selection).

≈ 5 cards × ≤2 models × ~1 h ≈ 8–10 GPU-hours; stock permitting.

### Phase 4 — Retrieval-side axes (optional, scoped after Phase 2 results)

Run only with the Phase 2 winner, on PRO 6000, same protocol:

4.1 Reranker: Qwen3-Reranker-0.6B (baseline) vs Qwen3-Reranker-4B vs
    `zeroentropy/zerank-2` vs bge-reranker-v2-m3; with `RETRIEVAL_TOP_K` 20 vs 40.
    No re-ingest needed.
4.2 Embedder (needs a second index): Qwen3-Embedding-8B vs Qwen3-Embedding-4B vs
    `nvidia/Nemotron-3-Embed-8B`. Only if 4.1 shows retrieval is the limiting stage.
4.3 Pipeline changes held back from the freeze (per-entity retrieval split for
    comparisons, graph index cache) as before/after pairs.

### Phase 5 — Analysis and report

5.1 Run `eval_report.py` over everything; human adjudication of all judge/human
    disagreements on the final leaderboard rows.
5.2 Error taxonomy per rung, hand-labelled from the judge's "wrong"/"partial" set:
    retrieval miss / wrong row-column in right table / unsupported claim /
    over-abstention / citation error / format-length.
5.3 Report (`docs/eval/REPORT-2026-xx.md`, plus a shareable page): executive summary;
    method (this plan, as executed, with deviations); golden set description and
    verification status; leaderboard with CIs; per-category tables; quality-vs-cost
    and quality-vs-latency frontiers; GPU table; error taxonomy with examples;
    threats to validity (judge bias, single corpus, nondeterminism, stock-driven
    substitutions); recommendations per VRAM tier; reproducibility appendix
    (manifests, commands, digests). Raw results and judge outputs committed under
    `eval/results/2026-xx-full/`.
5.4 Independent review: `/code-reviewer` on the harness; a second judge model on a
    20% sample to report judge-judge agreement; the user signs off the final
    adjudicated labels.

## 5. Metrics (definitions used throughout)

| Group | Metric | Definition |
|---|---|---|
| Retrieval | recall@20, recall@8 | expected docs present in hybrid top-20 / reranked top-8 |
| | MRR, nDCG@8 | rank of first expected doc; graded by page hit |
| | page hit | an expected page of an expected doc is in the top-8 |
| | distractor rate | a listed distractor doc was cited |
| Generation | correctness | judge label ∈ {correct, partial, wrong, abstained}; headline = correct rate on answerable Qs |
| Generation | correctness rules (user, 2026-10-13) | `correct` = the asked-for value(s) with units, extra context allowed; `partial` = right value with a minor deviation (rounding, a missing unit or one side of a comparison); `wrong` = a different value, INCLUDING an honestly labelled sibling-model value — a near-miss is wrong even when close; `abstained` = declined or said not enough information although the answer exists. Human grades C/C-/A/N/W map to correct/partial/abstained/wrong/wrong. |
| | confident-wrong rate | wrong ∧ not abstained — the metric that matters most for an engineering corpus |
| | faithfulness | supported claims ÷ all claims (claim-level) |
| | citation precision | cited sources that support a claim ÷ cited sources |
| | abstention accuracy | unanswerables declined ÷ unanswerables; answerables abstained ÷ answerables (over-abstention) |
| | comparison completeness | both sides cited and both values given |
| Efficiency | latency p50 / p90, TTFT, decode tok/s, per-stage ms | from the harness and the throughput probe; since 2026-10-15 also per model call: tokens each way, ms and end-to-end tok/s (includes prompt processing) by purpose (answer vs side calls) |
| | throughput@1/4/8 | aggregate tok/s and questions/min |
| | cost / 1,000 Q | wall time × on-demand rate, sequential and at 8 streams |
| | boot time, VRAM used | boot = POD UP request to ready (podlink `boot_s`, recorded by the campaign runner since 2026-10-14); VRAM = card memory in use, a manual reading of the RunPod console per rung until a pod-side `nvidia-smi` reading exists (RunPod's API reports memory bandwidth, not occupancy) |
| Stability | repeat agreement | fraction of questions with the same label across 3 repeats |
| Statistics | 95% bootstrap CI; McNemar vs baseline; κ judge-vs-human | reported for every headline number |

## 6. Budget and timeline (estimates, to verify against live rates)

| Item | Estimate |
|---|---|
| GPU time: Phase 2 (5 active rungs × OFF/ON; 2026-10-14) | ≈ 18–20 h × $2.49 ≈ $45–50 (the deferred 4B/8B rungs would add ≈ $15) |
| GPU time: Phase 3 (5 cards) | 8–10 h × $0.5–3 ≈ $15–25 |
| GPU time: Phase 0 re-ingest (119 docs, KG extraction) | ~1 h on PRO 6000 ≈ $2 |
| GPU time: Phase 4 if run | ~5 h ≈ $10 |
| Failed boots / stock retries / weight downloads | allow +30% |
| Judge: Opus 5.5 via Claude Code headless on the Max login (≈ 6,600 answers × 3 grading tasks, batched ~20 per call ≈ 1,000 calls) | $0 cash; subscription usage only, spread over several days/nights |
| Judge: GPT-5.x second opinion on a 20% sample + disagreements (Codex bridge) | ≈ $10–20 OpenAI |
| **Total** | **≈ $100–150 cash; cap $300 kept as the hard ceiling, stop-and-ask at $250 spent; Phase 4 runs if under** |
| Effort: Phase 0 (user verification + 40 new Qs) | the critical path; 2–4 working days of verification |
| Effort: Phase 1 | 2–3 days build + review |
| Phases 2–3 wall time | ~3–4 pod-days, can interleave with Phase 0 verification only for the harness dry-runs |
| Phase 5 | 2 days |

## 7. Risks and mitigations

- **Golden set still unverified** → nothing is frozen until v1.0; models disagreeing
  with the set are treated as a question, not a verdict (existing rule).
- **Run-to-run noise (≈ ±2 Q)** → 3 repeats, paired tests; 100 questions narrows the
  CI roughly from ±10 pts to ±8 pts on a 60-vs-100 basis — still wide; the report
  states it rather than hiding it.
- **Judge bias** → calibration κ, two judges on a sample, human adjudication on the
  final table; evidence-grounded grading rather than free comparison.
- **KG extraction depends on the LLM** → fixed extractor at index time (0.4);
  documented as a design limit (the ladder measures the generator only).
- **Secure-cloud stock** (H100/L40S/PRO 4500 availability flips) → ladder profiles
  with fallbacks; substitutions recorded in the manifest and the report.
- **sm_89/sm_90 image path untested** → boot check before committing GPU-hours.
- **Model landscape moves (Qwen4)** → ladder frozen; addendum rung protocol.
- **Secrets** → pod bearer travels to each pod; rotate after the campaign; results
  files already mask pod ids and redact URLs.
- **Parser licence** → 1.28.2 is AGPL-only; fine for this internal eval, noted in the
  report's reproducibility section.

## 8. Decisions needed before Phase 1 starts

All decided 2026-10-13:

1. **Judge:** Claude Opus 5.5 grades every answer (correctness, faithfulness, citation
   support), called through Claude Code headless mode (`claude -p --model
   claude-opus-5-5 --output-format json --json-schema … --tools "" --max-turns 1
   --no-session-persistence`) on the existing Max login — no Anthropic API key, no
   per-call billing; usage counts against the subscription's rolling limits, so the
   judge batches ~20 answers per call, retries on throttling and is resumable per run
   file. `--bare` is not usable (it drops the claude.ai login). The model id reported
   in each response is recorded. GPT-5.x via the existing Codex bridge re-grades a 20%
   random sample plus every judge-vs-human disagreement from the calibration set
   (billed OpenAI calls). Corpus is public vendor datasheets, so no
   data-leaving-the-building concern. Verified 2026-10-13: one grading call ≈ 32k
   context (mostly cache hits), 2.7 s.
2. **Defects:** fix both ingestion-content defects (D10 empty chunk, A09 blank table
   row) before the index freeze, each through plan → approval → implement. Retrieval-
   strategy changes stay out of the freeze.
3. **Scope:** HMI-only, 100 questions (confirmed 2026-10-12).
4. **GPU list:** all five cards (PRO 6000, H100 80GB, L40S, RTX A6000, PRO 4500).
5. **Rungs:** the six listed plus Qwen3-8B as rung 1b → seven rungs, each thinking
   OFF and ON, 3 repeats. **Revised 2026-10-14:** five active rungs (2, 3, 4, 5, 6);
   1 and 1b deferred, kept on record for a later run.
6. **Budget:** cap $300; stop and ask at $250 spent; Phase 4 runs only if the rest
   comes in under the cap.

## 9. Deliverables

- `eval/golden_set_hmi.json` v1.0 (100 Q, verified, digest in the report)
- `scripts/evaluate.py` v2, `scripts/eval_judge.py`, `scripts/eval_load.py`,
  `scripts/eval_report.py` with tests
- `eval/results/2026-xx-full/` raw runs + judge outputs + manifests
- `docs/eval/REPORT-2026-xx.md` and a shareable page
- podlink profiles for every rung/card under `deploy/profiles/eval/`
