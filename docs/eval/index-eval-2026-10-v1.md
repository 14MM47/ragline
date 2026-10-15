# Eval index `ragline_eval_v1` — digest (plan 0.4, built 2026-10-13/14)

The frozen index every rung of campaign `eval-2026-10` runs against. Never
re-ingested during the campaign; the campaign preflight refuses any other
point count (`[index].points` in `eval/campaign/eval-2026-10.toml`).

| Item | Value |
|---|---|
| Qdrant collection | `ragline_eval_v1` (4096-d, cosine; created before ingest with the prod collection's settings) |
| Metadata + knowledge graph | `data/ragline_eval_v1.db` (not in git) |
| Documents | 119 ready (the HMI corpus, `testdata/hmi`, source paths `hmi/<vendor>/…`) |
| Chunks / vectors | 15,064 / 15,064 |
| Entities / relationships | 76,279 / 172,712 |
| Parser | pymupdf4llm 1.28.2, pymupdf 1.28.2, OCR fallback on (Tesseract 5.3.4), layout analysis on |
| Chunker | table-aware structural chunker (commit 4005b16): 512-token budget, 15% prose overlap, table rows atomic with header repetition, CHUNK_MIN_TOKENS 48 |
| Embedder | Qwen/Qwen3-Embedding-8B (pod TEI) |
| KG extractor | stelterlab/Qwen3-30B-A3B-Instruct-2507-AWQ, KG_EXTRACTION_MAX_TOKENS 4096, concurrency 32 |
| Build | 50 documents in one session (thread-pool parsing), 69 from the parse cache (`d8a50c5d1dd0`) in a second; GPU cost $9.73 over three pod sessions incl. one aborted attempt and the smoke pass (ledger `eval/results/eval-2026-10/spend.jsonl`) |

## Checks (step 7)

- **A09** — the one chunk of `panelview_5500_technical_data.pdf` p.3 holding
  `512 MB RAM` also holds the `2715-T7CD` header row: pass.
- **D10** — `emt3070a_7in_datasheet.pdf` has three chunks (226, 433, 585
  tokens); none under 48; the 226-token p.1 chunk carries the operating
  temperature: pass.
- Qdrant points equal chunk records (15,064); no document with zero chunks.

## Chunk statistics, prod index `ragline_pod` vs this index

| | `ragline_pod` (old chunker, 1.28.0) | `ragline_eval_v1` |
|---|---|---|
| Chunks | 14,937 | 15,064 |
| Tokens (sum over chunks) | 4,541,946 | 4,577,260 (+0.8%) |
| Chunks under 48 tokens | 677 | 439 (the rest are pages whose only chunk is short) |
| Chunks whose first or last line is a cut table row | 1,694 | 62 |
| Table chunks opening with rows and no header | 1 | 42 |

Reading the last two rows: the old chunker cut inside rows, so its
continuation chunks began with a fragment, not a row (counted in the cut-row
line). The new chunker cuts only between rows; the 42 header-less openings
are continuations of tables that have no `|---|` header to repeat. The 62
remaining "cut row" edges are lines with pipe characters in prose or in
pymupdf4llm picture text, not table rows.

## Known constants (identical for every rung)

- KG extraction produced no graph for ≈ 3.5% of chunks (616 of ≈ 17,450
  extraction calls, the count including the aborted attempt's in-flight
  documents): ≈ 2.7% truncated at 4096 output tokens on dense tables, the
  rest malformed JSON.
- Layout analysis replaces pymupdf4llm markdown with reading-order text on
  pages it classes as multi-column (also true of the prod index).
- pymupdf4llm places spanning table cells on one row only (PanelView 5500
  user manual p.16); the tech-data table answers A09 instead.

## Smoke pass (unjudged, not a campaign result)

One `--path rag` pass of the 100 golden questions on the build pod
(Qwen3-30B-A3B-Instruct-2507-AWQ, thinking off), 2026-10-14 10:10–10:33:
0 errors, 0 declined, median latency 8.0 s.

| Metric | Value |
|---|---|
| Source hit (expected document cited, `all` rule for comparisons) | 58 / 87 scored (66.7%) |
| recall@20 / recall@8 / MRR / nDCG@8 | 0.931 / 0.880 / 0.838 / 0.758 |
| Page hit | 0.920 |
| Misses by category | comparison 13 of 18, spec 7, multihop 7, follow-up 2 |

Not comparable with the September 42–45/51 runs (different question set,
generator and index). Comparisons dominate the misses: one query embedding
lands on one product, so the second product's document is often not cited.

**A09 and D10 still fail end to end, for retrieval reasons.** The chunk fixes
hold in the index, but:
- A09: the retriever returned page 3's first chunk (display rows) rather
  than the memory chunk, which did not reach the top 20; the model then took
  "1 GB" from the PanelView 5510 technical data — a confident wrong answer.
- D10: the eMT3070A datasheet did not reach the top 20 at all; only the
  eMT3150A side of the comparison was retrieved.
Both are ranking problems (plan §5 risk), the retrieval-strategy axis the
evaluation plan keeps out of the freeze (Phase 4: per-entity retrieval for
comparisons). They stay in the golden set as measured failures.
