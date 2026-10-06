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

[`eval/golden_set_hmi.json`](../eval/golden_set_hmi.json) — 60 questions:

| Category | Count | What it tests |
|---|---:|---|
| `spec` | 36 | A single fact from a single document |
| `comparison` | 10 | A fact about each of two products, usually in two documents |
| `unanswerable` | 6 | Something the corpus does not contain; the right answer is to say so |
| `followup` | 5 | A question that only makes sense after a previous turn |
| `library` | 3 | A question about the collection, not about a document's contents |

Each entry carries:

| Field | Meaning |
|---|---|
| `id`, `category`, `tags` | Identity and grouping |
| `question`, `expected_answer` | What is asked and what a correct answer says |
| `expected_sources` | Corpus-relative paths of the documents the answer comes from |
| `source_match` | `any` — citing one listed source is a hit; `all` — every one must be cited; `none` — no source is expected (not scored for hit-rate) |
| `expected_pages`, `evidence` | The page and the quoted line that support the expected answer |
| `review_note` | Why a human should double-check this entry |
| `history` | For follow-ups, the previous turn |
| `absence_check`, `library_truth`, `distractor_*` | Supporting data for unanswerable, library and deliberately confusable questions |

The set was drafted with model assistance from the documents and is being
checked by hand against the PDFs. [The review sheet](../eval/golden_set_hmi_review.md)
tracks that: 8 of 60 entries are verified so far, and the first analysis
flagged three expected answers (A01, D02, C11) that may themselves be wrong.
Treat a disagreement between a model and the set as a question, not a verdict.

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

Each question goes through the full answer path — retrieval, rerank, graph
context, generation, citation extraction — exactly as a one-shot query from
the UI would.

## What is measured automatically

- **Source hit** — did the answer cite the expected document(s), under the
  entry's `source_match` rule? Matching is by file name.
- **Cited** — did the answer carry at least one valid citation?
- **Page sanity** — is every cited page within its document's page count?
- **Latency and tokens** per question, and **per-stage timings** (query
  embedding, vector search, sparse merge, rerank, graph context, answer
  generation, citation extraction).

The results file also records the run: label, time, model names, endpoint
hosts (RunPod pod ids are masked), the ragline revision and a digest of the
golden set — enough to know later whether two runs are comparable. Pod ids
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

- **Whether the answer is right.** The script records the answer beside the
  expected one; grading is by hand. This matters: in the first recorded run
  six of the 45 "hits" were not correct answers — three abstentions that
  cited the right document, three wrong values read from it.
- **Follow-ups in context.** The `history` field is not yet replayed, so the
  five follow-up questions are asked cold. Their numbers are not meaningful.
- **Library questions.** They are routed to the metadata database only in
  chat; the evaluator runs the retrieval path, so expect 0 of 3.

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
