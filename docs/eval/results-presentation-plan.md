# Plan — presenting the evaluation results to drive ragline's configuration

Status: APPROVED 2026-10-15 — headline = correct (plus correct + ½ partial alongside); dashboard as a private claude.ai page AND a local HTML file; build on rung 2 data. Sequenced after the rung 2 failure analysis (the user's item 4). Medium (report script + a new
dashboard generator + one published dashboard page; no change to ragline itself).

## Goal

Turn the campaign's results into the decisions they exist to inform — which
generator, which GPU tier, thinking on or off (and for which questions), and
what to fix in ragline next — with every number carrying its uncertainty, and
the views growing as rungs 3–6 and the GPU axis land. Two outputs from one data
build:

- **Static report** (`REPORT.md` + SVG figures, in git): the frozen, citable
  record; extended from today's `scripts/eval_report.py`.
- **Interactive dashboard** (one HTML page, published as a private claude.ai
  artifact, regenerated after every rung): the working tool for exploring,
  filtering and drilling into individual answers.

## What rung 2 already shows (and why each view is needed)

| Finding (rung 2, Qwen3.8-27B, 3 repeats each) | View that makes it visible |
|---|---|
| Thinking ON is +3 pts correct (71.1 % vs 68.1 %) but cites the expected document *less* (0.72 vs 0.77) | Correctness and citation side by side; source-hit alone would have ranked the conditions backwards |
| The gain is partials becoming correct (51 → 40 partial, 184 → 192 correct); abstentions rise (18 → 24) | Verdict-mix bars per configuration |
| By category it is flat on spec (n = 48) and comparisons (18), slightly up on follow-ups and library, slightly down on multi-hop — small n everywhere but spec | Category × configuration heatmap with per-cell n and CI |
| Nearly every failure is on the generation side: the expected document was in the reranked top-8 for 10 of 11 OFF and 11 of 13 ON failures | Failure attribution: retrieval miss vs generation-with-right-documents — directly says "fix answering/table reading, not retrieval" |
| Long reasoning predicts failure: median reasoning 1.5k chars when correct, 6.7k partial, 13.5k wrong | Reasoning length vs verdict — a candidate confidence / routing signal for ragline |
| The knowledge-graph stage is the slowest stage (median 5.1 s OFF, 7.4 s ON) — slower than the OFF answer itself (2.9 s) | Stage-latency breakdown — puts the known "graph index rebuilt per query" fix at the top of the latency list |
| Thinking costs 2.2× median latency (25 s vs 11 s) and 3× fewer questions/min at 1 stream | Quality vs latency / cost frontier |
| 94–96 of 100 questions get the same label in all three repeats | Stability per configuration; flags the few unstable questions |

## The views

Ordered by the decision they serve. ★ = in both outputs; ◆ = dashboard only.

**1. Decide: which configuration**
1. ★ **Decision table** — per model × condition: correct (95 % CI),
   confident-wrong rate, partial, abstained, unanswerables declined,
   faithfulness, citation support, latency p50/p90, $/1,000 Q, GPU memory,
   VRAM tier (24/48/96 GB), boot time. Sortable; a "best per tier" marker.
2. ★ **Quality–cost frontier** — correct vs $/1,000 Q (and vs latency p50), one
   point per configuration, ○ OFF / △ ON, CI bars, Pareto front drawn; points
   grouped by VRAM tier.
3. ★ **Paired comparisons** — every configuration vs the baseline and ON vs OFF
   per model: difference with paired-bootstrap CI and McNemar p, as a forest
   plot (one row per comparison).

**2. Decide: thinking on or off, and where**
4. ★ **Thinking effect per model** (already a figure) plus the verdict-mix shift
   (correct / partial / wrong / abstained).
5. ★ **Category × configuration heatmap** — correct rate with n per cell; a
   second panel shows the ON − OFF difference per category.
6. ★ **Reasoning length vs verdict** — box plot per verdict, per model; the
   cost side as reasoning tokens per answer.

**3. Decide: what to fix in ragline**
7. ★ **Failure attribution** — every wrong/abstained/partial answer split into:
   expected document not retrieved (top-20) / retrieved but not reranked into
   the top-8 / in the top-8 but answered wrongly; per configuration and
   category. Later joined with the hand-checked error taxonomy (plan 5.2).
8. ★ **Stage latency breakdown** — stacked bar per configuration: pre-pass,
   embedding, search, rerank, graph, answer, side calls.
9. ★ **Retrieval quality by category** (existing figure) — recall@8 / nDCG.

**4. Trust: how solid is each number**
10. ★ **Stability** — share of questions with the same label across repeats;
    list of unstable questions.
11. ★ **Judge reliability** — judge vs human κ (0.883), judge vs GPT second
    opinion agreement on the 20 % sample, adjudication status.
12. ★ **Spend and run log** — per rung and session, with deviations from
    NOTES.md.

**5. Explore (dashboard)**
13. ◆ **Question grid** — rows = 100 questions, columns = configurations ×
    repeats, cells coloured by verdict; filter by category / tag / verdict /
    "flips between conditions"; click a cell for the question, expected answer,
    the answer given, citations, judge reason, unsupported claims, retrieval
    ranks, reasoning length and timing.
14. ◆ **Speed under load** — questions/min and latency vs concurrency (1/4/8)
    per configuration.

Transcripts stay local (option B): the dashboard shows each answer, not the
full prompt and reasoning; a cell shows the command to open its transcript
with `scripts/eval_transcript.py`.

## Implementation

1. `scripts/eval_report.py`: add the missing metrics — confident-wrong rate,
   repeat stability, comparison completeness (from the existing plan, §5) —
   and the new analyses: failure attribution, reasoning vs verdict, stage
   breakdown, Pareto front, forest plot, verdict mix, ON − OFF category
   heatmap, GPU memory and tier (from NOTES.md readings, moved into a small
   `eval/results/<campaign>/measurements.toml` so they are machine-readable).
   Export everything the dashboard needs as `dashboard.json` (per-question
   rows without transcript text: ≈ 1 KB × 100 questions × passes — ≈ 4 MB for
   the full five-rung campaign).
2. `scripts/eval_dashboard.py` → one self-contained HTML page (charts drawn
   in the page from `dashboard.json`), published as a private artifact and
   republished to the same link after each rung. The page has sections in the
   order above, works on a phone, light/dark.
3. Rung gate (per-rung protocol step 6–7): after judging, regenerate REPORT.md
   and the dashboard; the gate summary links both.
4. Tests on the new analyses with the existing synthetic campaign fixture.

Privacy note: the dashboard contains questions, answers and short corpus
excerpts (public vendor documentation) — no transcripts, prompts or keys. It
is private on claude.ai until shared.

## Decisions for the user

1. **Partial credit in the headline**: today's correct rate counts partial as
   0 (your rule: minor deviation = partial). Recommend showing both "correct"
   and "correct + ½ partial", with "correct" as the headline.
2. **Dashboard hosting**: a private claude.ai artifact (recommended: one link,
   updated each rung) or a local HTML file only.
3. **Build now on rung 2's data** (recommended: the views are designed against
   real numbers and ready when rung 3 lands) or after rung 3.
