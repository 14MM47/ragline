# Evaluation

The evaluation harness answers one question: *given the same documents and
the same questions, what changes when the model stack does?* It has three
parts — a corpus, a golden question set, and a script that runs one against
the other and records what happened.

## The corpus

803 datasheets, manuals and catalogues for industrial automation equipment,
in a tree of `<category>/<vendor>/<product-family>/<file>.pdf`. The PDFs are
not in the repository; [eval/corpus/](../eval/corpus/README.md) explains why
and indexes them, and `scripts/fetch_corpus.py` downloads them.

The recorded runs use the `hmi/` category only: 119 documents, about 11,700
pages. It was chosen because HMI panels come in families of near-identical
models whose datasheets differ by a row or a column — which is exactly what
makes retrieval and table reading hard.

```bash
.venv/bin/python scripts/fetch_corpus.py --category hmi
.venv/bin/python scripts/ingest.py testdata/hmi
```

Ingest the whole category, not just the documents the questions cite: the
other documents are the distractors the retriever has to see past.

## The golden set

[`eval/golden_set_hmi.json`](../eval/golden_set_hmi.json) — 100 questions:

| Category | Count | What it tests |
|---|---:|---|
| `spec` | 48 | A single fact from a single document |
| `comparison` | 18 | A fact about each of two products, usually in two documents; both must be cited |
| `multihop` | 8 | An answer that needs two or more chunks: which of these models…, a table value plus a footnote elsewhere |
| `procedure` | 8 | An ordered how-to from a manual (battery, mounting, calibration, installation) |
| `unanswerable` | 10 | Something the corpus does not contain; the right answer is to say so |
| `followup` | 5 | A question that only makes sense after a previous turn |
| `library` | 3 | A question about the collection, not about a document's contents |

Ids: `A`–`D` are spec and comparison questions by vendor group (Allen-Bradley;
Siemens/Beckhoff/Advantech; Mitsubishi/Omron/Delta; the rest), `E` unanswerable
and library, `F` follow-ups, `G` multihop, `H` procedures. The 40 questions added
on 2026-10-12 (A13–A17, B12–B16, C12–C16, D13–D17, E10–E13, G01–G08, H01–H08) were
drafted from the PDFs with model assistance and every evidence quote was checked
programmatically against the extracted page text.

Each entry carries:

| Field | Meaning |
|---|---|
| `id`, `category`, `tags` | Identity and grouping |
| `question`, `expected_answer` | What is asked and what a correct answer says |
| `expected_sources` | Corpus-relative paths of the documents the answer comes from |
| `source_match` | `any` — citing one listed source is a hit; `all` — every one must be cited; `none` — no source is expected (not scored for hit-rate) |
| `expected_pages`, `evidence` | The page and the quoted line that support the expected answer |
| `review_note` | Why a human should double-check this entry |
| `difficulty` | (new entries) `table` — value read by row/column position in a flattened table; `distractor` — a near-identical sibling model exists with a different value; `long-doc` — manual over 100 pages; `easy` |
| `history` | For follow-ups, the previous turn |
| `absence_check`, `library_truth`, `distractor_*` | Supporting data for unanswerable, library and deliberately confusable questions |

The set was drafted with model assistance from the documents and every entry was
then checked by hand against the PDFs (completed 2026-10-13; [the review
sheet](../eval/golden_set_hmi_review.md) records the ticks). The review found one
discrepancy, A06, where a newer document adds a UK UKEX sibling certificate next
to the ATEX one; its expected answer now names that number as a wrong substitute.
A disagreement between a model and the set is still worth a look, but the set is
the reference.

`eval/examples/golden_example.json` shows the minimal format.
`eval/golden_set_all_categories.draft.json` is an unreviewed 50-question draft
across all nine categories, kept as a starting point.

## Running it

Requires Qdrant up, the corpus ingested, and `.env` pointing at the stack
under test.

```bash
.venv/bin/python scripts/evaluate.py eval/golden_set_hmi.json \
    -o eval/results/$(date +%F)_<stack>.json --label <stack> \
    2>&1 | tee eval/results/$(date +%F)_<stack>.log
```

`--threshold 0.7` makes the script exit non-zero when the hit-rate falls
below that value.

Two answer paths. `--path rag` (the default) sends each question through
`RAGAgent.query()` — retrieval, rerank, graph context, generation, citation
extraction — exactly as a one-shot `/query` call would; follow-ups are asked
cold and flagged `history_replayed: false`. `--path chat` sends each question
through `ChatAgent.chat()` in a fresh session seeded with the entry's
`history` turns, so the pre-pass, query rewrite and library routing run as
they do in the UI; evaluation sessions live in a temporary directory, never
in the app's memory store.

Campaign options, used by the evaluation plan's runner and fine by hand:

| Option | Effect |
|---|---|
| `--repeats N` | N full passes; one results file per pass (`<output>_r<N>.json`) |
| `--warmup K` | K questions asked and discarded first, so cold caches stay out of pass 1 |
| `--campaign C --rung R --condition X` | Results go to `eval/results/C/R/X/r<N>.json` (`--output-dir` changes the root) |
| `--manifest-extra '{…}'` or `@file` | GPU, rate, vLLM arguments… recorded in the run manifest; never guessed |
| `--thinking off\|on\|unset` | Overrides the thinking mode recorded (default: read from `LLM_EXTRA_BODY`) |

Exit codes: 0; 1 when the hit-rate is below `--threshold`; 2 when raw
`<think>` text reached an answer — the condition is invalid regardless of its
scores, and the fix is starting vLLM with the model's reasoning parser.

### Throughput probe

`scripts/eval_load.py` asks a fixed 24-question subset of the golden set
(category- and vendor-balanced, follow-ups and library questions excluded)
at 1, 4 and 8 concurrent streams and records, per level, questions per
minute, latency median/p90/max, answer tok/s and errors; then streams the
real answer prompt for each question at the same levels to measure time to
first token and decode tok/s under load. It needs an LLM endpoint whose
`max_num_seqs` is at least the highest level; queueing shows up as latency,
rejections as errors, neither is hidden.

```bash
.venv/bin/python scripts/eval_load.py eval/golden_set_hmi.json -o eval/results/<run>/load.json
```

### Grading the answers

`scripts/eval_judge.py` grades a results file offline with a frontier model
through Claude Code's headless mode on the existing login (no API key): for
each answer, correctness against the golden entry's expected answer and
evidence quotes (`correct` / `partial` / `wrong` / `abstained`; unanswerable
entries report `declined` / `answered_wrong`), the answer's factual claims
each marked supported or not by the retrieved passages (fetched from Qdrant
by chunk id, so the run's index must still be loaded), and whether each
citation is actually used. The rubric is in `eval/judge_prompts/` and its
hash is recorded with every grade. Output is `<results>.judge.json` beside the
results file; re-running skips what is already graded.

```bash
.venv/bin/python scripts/eval_judge.py eval/results/<run>.json
.venv/bin/python scripts/eval_judge.py eval/results/<run>.json \
    --calibrate eval/human_grades_2026-09-28.json     # kappa vs the hand grades
```

Calibration on 2026-10-13: Cohen's kappa 0.883 between the judge (Opus 5.5,
rubric `ad926a73b52a`) and the 46 hand grades of the 2026-09-28 run, with
two disagreements (B11, D10: comparisons where one side was answered and
the other not retrieved; the hand grade said abstained, the rubric says
partial).

### Running a campaign rung

`scripts/eval_campaign.py` runs one rung of a campaign defined in
`eval/campaign/<name>.toml` (models, conditions, repeats, budget) against the
podlink console on localhost, following the per-rung protocol in the
[evaluation plan](evaluation-plan.md): spend gate, profile preflight, pod up
and the four readiness checks, each condition's `.env` variables merged with
the handoff hook's own routine, `evaluate.py` and `eval_load.py` per
condition, pod down (terminate) with the session cost appended to
`eval/results/<campaign>/spend.jsonl`, then `eval_judge.py` offline and a
`SUMMARY.md` for the gate. It never chains rungs; the next one is a new
invocation after review. `--dry-run` exercises the whole flow on a fake
console without spending anything.

```bash
.venv/bin/python scripts/eval_campaign.py eval/campaign/eval-2026-10.toml --rung r2 --dry-run
.venv/bin/python scripts/eval_campaign.py eval/campaign/eval-2026-10.toml --rung r2
```

The podlink profiles for the rungs are in podlink's `deploy/profiles/eval/`
(examples) and must be installed under `~/.config/podlink/profiles/`;
`start.sh --check --profile <name>` is what the runner's preflight calls.

### The campaign report

`scripts/eval_report.py eval/results/<campaign>` aggregates every run, judge
file, probe and the spend ledger into `report.json`, SVG figures and a
`REPORT.md` of tables: correctness per configuration with 95 % bootstrap
CIs (10,000 samples over questions, seeded), paired comparisons against the
baseline and thinking ON vs OFF with McNemar's exact test on majority-vote
correctness, category and retrieval breakdowns, latency, throughput and cost
per 1,000 questions, run health and spend. Figures need matplotlib (in the
`dev` extra); without it the markdown is still written.

## What is measured automatically

- **Source hit** — did the answer cite the expected document(s), under the
  entry's `source_match` rule? Matching is by file name.
- **Cited** — did the answer carry at least one valid citation?
- **Page sanity** — is every cited page within its document's page count?
- **Retrieval, before generation** — the fused top-20 candidates and the
  reranked top-8 are recorded per question (file, pages, chunk id, score) and
  scored against the entry's expected documents and pages: recall@20 and
  recall@8 (documents), MRR and nDCG@8 on the reranked list (relevance 2 for
  an expected page of an expected document, 1 for the document alone, with
  the ideal list being one chunk per expected document), page hit, and
  whether a listed distractor document was retrieved or cited. Entries with
  nothing expected score `null`.
- **Declined** — the answer used refusal wording and cited nothing. A cited
  "the documents do not state…" is a grounded negative and is left to grading.
- **Think residue** — raw thinking markup in the answer (must be zero).
- **Latency and tokens** per question, hidden-reasoning length
  (`reasoning_chars`, thinking models only), and **per-stage timings** (query
  embedding, vector search, sparse merge, rerank, graph context, answer
  generation, citation extraction).

The results file also records the run: label, time, model names, endpoint
hosts (RunPod pod ids are masked), the ragline revision, a digest of the
golden set, the answer path, thinking mode and `LLM_EXTRA_BODY`, the
retrieval and rerank top-k, the parser version, the Qdrant collection and its
point count, repeat number, and whatever `--manifest-extra` supplied — enough
to know later whether two runs are comparable. Pod ids
are also masked in structured logs, HTTP-client logs and saved error messages;
URL credentials are redacted. That masking covers string fields in
structured logs and everything written through the root logger's handlers
present at startup. It does not reach a value that is not a string, list,
tuple or dict (an exception object logged as a field, for instance), a
traceback rendered by structlog (`exc_info=True`), or a log handler attached
later — so check before sharing a log:

```bash
grep -nE '[a-z0-9]-[0-9]+\.proxy\.runpod\.net' eval/results/<run>.log    # expect no output
```

External golden-set paths are recorded by file
name so an absolute path does not publish your home directory. Review answers
and document content before sharing: endpoint redaction does not remove
sensitive information from the documents being evaluated.

## What is not

- **Whether the answer is right, by the harness itself.** The script records
  the answer beside the expected one; grading is a separate step
  (`eval_judge.py` above, or by hand). This matters: in the first recorded
  run six of the 45 "hits" were not correct answers — three abstentions that
  cited the right document, three wrong values read from it.
- **Follow-ups on the rag path.** With `--path rag` the five follow-up
  questions are asked cold and their numbers are not meaningful; use
  `--path chat`, which replays the `history` turns.
- **Library questions on the rag path.** They are routed to the metadata
  database only in chat, so on `--path rag` expect 0 of 3; `--path chat`
  measures them.

## Reading a result

[eval/results/](../eval/results/README.md) holds the recorded runs and a
hand-graded analysis of the first two. Things learned from them that apply to
any new run:

- A one- or two-question change in hit-rate between runs of the same stack is
  noise: the same weights on a different GPU generation produce slightly
  different logits, and a correct answer that cites a sibling document counts
  as a miss.
- Wrong answers so far are table-reading errors inside the right document,
  not retrieval failures or inventions. If a new stack reads the same tables
  correctly, the model was the limit; if it makes the same mistakes, parsing
  and chunking are.
- Abstentions trace to retrieval or to chunk content (a table row that came
  out blank, a section that never made the top 8), not to the model.

## Comparing two stacks

1. Keep the collection: same embedder, same ingested corpus. If the embedder
   differs, use a separate collection, SQLite database and storage directory,
   [ingest again](gpu-pod.md#changing-the-embedder-means-re-ingesting), and say
   so in the label.
2. Run the same golden set file — the digest in the results confirms it.
3. Compare per question (`id`), not just the totals, and grade the answers
   that differ.
