# Recorded runs

Each run is a pair of files written by `scripts/evaluate.py`: `<date>_<label>.json`
(the scores, the stack, and every question's answer, citations, latency and
tokens) and `<date>_<label>.log` (the pipeline's own log for the run).
[docs/evaluation.md](../../docs/evaluation.md) explains the method and what
the scores do and do not mean.

All four runs use the same stack and the same golden set
(`eval/golden_set_hmi.json`, digest `cd6b80d7b1bb`), over the 119 documents of
the `hmi/` corpus category:

- LLM `RedHatAI/Qwen3.8-27B-INT4`, thinking off, served by vLLM as `ragline-llm`
- embedder `Qwen/Qwen3-Embedding-8B` (4096-dim) on TEI
- reranker `Qwen/Qwen3-Reranker-0.6B` on vLLM (`RERANKER_API_FORMAT=cohere`)
- all three on one GPU

| Run | GPU | What changed | Source hit-rate | Cited | Median latency | Whole set | Tokens |
|---|---|---|---|---|---|---|---|
| `2026-09-28_ragline-3090-on6000` | 1× RTX PRO 6000 | first baseline | 45 / 51 (0.88) | 60 / 60 | 6.5 s | 7.6 min | 292k |
| `2026-09-29_ragline-3090-on-a6000` | 1× RTX A6000 | same stack, slower card | 44 / 51 (0.86) | 60 / 60 | 11.6 s | 14.0 min | 293k |
| `2026-10-02_…_answer-length` | 1× RTX A6000 | answer-length rule in the prompt | 43 / 51 (0.84) | 56 / 60 | 11.9 s | 12.6 min | 291k |
| `2026-10-02_…_step-timing` | 1× RTX A6000 | per-stage timing recorded | 42 / 51 (0.82) | 58 / 60 | 10.7 s | 12.0 min | 291k |

The hit-rate is scored on the 51 questions that name an expected source; the
other nine (unanswerable and library questions) have none. The answer-length
rule roughly halved the median completion (about 140 → 80 tokens) without a
matching drop in latency — at this size the time is in retrieval, graph
context and prompt processing as much as in decoding.

Per-stage medians from the last run (A6000), in milliseconds:

| embed query | vector search | sparse merge | rerank | graph context | answer | citations |
|---:|---:|---:|---:|---:|---:|---:|
| 707 | 12 | 63 | 1,425 | 2,578 | 5,446 | 1 |

[2026-09-28_analysis.md](2026-09-28_analysis.md) grades the first two runs by
hand, question by question: 37 of 46 answerable questions correct, three
confidently wrong (all table misreads in the right document), all six
unanswerable questions declined.

## Reading the files

- **All four runs were ingested with parser version 1.28.0** (`pymupdf4llm`),
  under the ingestion worker's threaded parsing. The repository now pins
  1.28.2, which produces different page text on most single-column pages
  (retaining slightly more of it overall), assigns a different section
  heading to roughly one page in five, and — unlike 1.28.0 — gives the same
  output whether documents are parsed one at a time or in threads. An index
  built today is therefore not the index these runs queried. In a comparison
  over 1,605 corpus pages the golden set's quoted evidence was found on the
  expected page equally often under both versions, so the results should
  carry over within run-to-run noise, but that has not yet been confirmed by
  a fresh ingest and run.

- **`run.ragline_rev`** is a commit in the project's pre-publication history
  and does not exist in this repository. It is kept so the runs can be told
  apart; from the first public release on, the revision is a real commit here.
- **Endpoint hosts** have the RunPod pod id masked (`<pod-id>-8000.proxy.runpod.net`).
- **`2026-09-28`** was re-scored after the run under the golden set's
  per-question `source_match` rule; its original stricter scores are kept as
  `hit_rate_all_sources` and `source_hit_all_sources`.
- **Answers quote the documents.** The results reproduce short passages of
  vendor datasheets as part of the answers being evaluated.

## Adding a run

```bash
.venv/bin/python scripts/evaluate.py eval/golden_set_hmi.json \
    -o eval/results/$(date +%F)_<label>.json --label <label> \
    2>&1 | tee eval/results/$(date +%F)_<label>.log
```

Name the label after the stack and the card, and add a row to the table above.
