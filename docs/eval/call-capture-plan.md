# Plan — per-call records, evaluation transcripts, answer settings in the manifest

Status: APPROVED 2026-10-15 (option B + archive to the Windows drive) and implemented on branch
feature/call-capture. Archive root: /mnt/c/Users/<user>/Documents/ragline-eval-archive. Medium (ragline tracing + model
client, the eval harness, the campaign runner, the report; tests). Wanted
before rung 3: rung 2 is recorded without these and is not re-run for them.

## Why

To compare thinking ON and OFF on every axis — tokens each way, tokens per
second, time, the full exchange and accuracy — per model. Today
(`eval/results/<campaign>/<rung>/<cond>/rN.json`, judged in `rN.judge.json`):

| Wanted | Today | Gap |
|---|---|---|
| Tokens each way | prompt / completion per question, summed over all its model calls | no split by call (pre-pass vs answer vs side calls) |
| Tokens per second | only approximable (turn completion tokens ÷ answer stage ms); true decode and TTFT only in the 24-question throughput probe | no per-call rate |
| Time | per question + per stage (`step_ms`) | none |
| Full exchange | question, rewritten query, answer, citations, retrieved chunk ids/scores | prompts sent, reasoning text and side-call outputs not kept (reasoning counted only — a Phase 1 privacy choice) |
| Accuracy | judge correctness / faithfulness / citation support, retrieval metrics | none |
| Settings | condition env inside `run.extra.condition_env` | answer settings not first-class in the manifest |

## Steps

1. **Per-call records** (`src/ragline/tracing/collector.py`,
   `src/ragline/llm/openai_provider.py`). `TraceCollector.calls: list[dict]`;
   the provider appends one entry per model call (complete, complete_json,
   stream): `purpose` (prepass, answer, library_answer, memory, confidence,
   kg, or "" for unlabelled), `answer` flag, `prompt_tokens`,
   `completion_tokens`, `reasoning_chars`, `ms` (wall time of the request),
   `finish_reason`, `max_tokens`, `temperature`, and for streamed calls
   `ttft_ms`. Derived per call: `tok_s = completion_tokens / (ms / 1000)` —
   end-to-end rate including prefill; labelled as such (true decode rate stays
   with the throughput probe). Always on: a dozen numbers per call, no text.
   Existing whole-turn totals unchanged.
2. **Harness** (`scripts/evaluate.py`): each per-question record gains
   `calls` (the list above); the pass summary gains, per purpose, total
   prompt/completion tokens, call count and median `tok_s`; and the answer
   call's median `tok_s` and `ms`. Pass-level token totals by purpose make
   the ON/OFF "tokens each way" comparison exact.
3. **Evaluation transcripts, opt-in** (new setting `LLM_CAPTURE_TRANSCRIPTS`,
   default off; documented as evaluation-only). When on, each `calls` entry
   also carries `messages` (exactly what was sent), `response` (content) and
   `reasoning` (the separated reasoning text). `evaluate.py` moves these text
   fields out of the results JSON into a sidecar
   `rN.transcripts.jsonl.gz` (one line per question: id + its calls), so the
   results files stay small and the judge/report read them as today. Estimate
   ≈ 30 KB raw per question (≈ 5.4k prompt tokens + reasoning) → ≈ 0.8 MB
   gzipped per pass, ≈ 30 MB for the whole five-rung campaign. The setting
   reverses the "reasoning text is never stored" rule only while on;
   production stays off. Secrets: messages hold prompts and corpus text
   only, but the sidecar still goes through the same redaction as the run
   log (hosts, keys).
4. **Campaign** (`scripts/eval_campaign.py`, `eval/campaign/eval-2026-10.toml`):
   a `[capture] transcripts = true` switch; the runner passes
   `LLM_CAPTURE_TRANSCRIPTS=1` in the pinned process environment of the
   evaluate runs only (like the index pin — `.env` untouched, probe and
   judge unaffected).
5. **Manifest** (`scripts/evaluate.py`): first-class run fields for
   `answer_extra_body`, `answer_temperature`, `answer_max_tokens`,
   `library_answer_max_tokens`, the three side-call ceilings,
   `llm_slow_call_s` and `transcripts` (on/off), next to the existing
   `llm_extra_body` and `thinking`.
6. **Report** (`scripts/eval_report.py`): per configuration, answer-call
   median tokens/s and time; a tokens-by-purpose table (prompt and
   completion, answer vs side calls) for ON vs OFF; reasoning tokens per
   answer. Runs without `calls` (rung 2) fall back to the current
   approximations, marked as such. Plus `scripts/eval_transcript.py <run>
   <id>` to print one question's full exchange from a sidecar, for error
   analysis.
7. **Tests**: per-call entries for each call shape and purpose (fake SDK);
   transcripts present only with the setting on and moved to the sidecar;
   redaction of the sidecar; manifest fields; report fallback for runs
   without `calls`; the campaign switch reaches only evaluate runs.
8. **Docs**: configuration (new setting), the harness README section, the
   evaluation plan's metric definitions (per-call tok/s = end-to-end rate).

## Decisions for the user

- **Transcripts in git or not.** ≈ 30 MB gzipped for the campaign. Option A:
  commit them with the results (complete, reproducible record; repo grows).
  Option B (recommended): keep them out of git (`*.transcripts.jsonl.gz` in
  `.gitignore`) and archive them with the eval index backup; results and
  judge files stay in git as now.
- **Rung 2 stays as recorded** (no per-call data, no transcripts); the report
  uses the approximations for it, marked.

## Out of scope

Streaming the answer call in the harness to get a true TTFT per question
(changes the code path under test; the throughput probe measures TTFT).
Storing transcripts in production.

## Implementation notes (2026-10-15)

- Per-call records: `TraceCollector.calls`, filled by the provider for every
  complete / complete_json / stream call; the chat agent passes them out as
  `llm_calls`; KG extraction is labelled `kg`. `tok_s` is end to end.
- Found and fixed while wiring the manifest: the harness labelled runs
  "thinking off" from LLM_EXTRA_BODY alone, so rung 2's ON files (answer-only
  thinking) say `thinking: off`. The harness now takes the answer body first;
  the report's `thinking_of()` repairs older manifests from the condition env,
  so rung 2's recorded files are left as they are.
- Archive: `scripts/eval_archive.py transcripts|index`; the runner archives the
  campaign's transcripts after every rung (`[archive] dest`), aborts included.
  The eval index (Qdrant snapshot + 6.8 GB SQLite DB) is archived once by hand.
- Transcript viewer: `scripts/eval_transcript.py <sidecar> <id>`.
