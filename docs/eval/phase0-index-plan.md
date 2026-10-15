# Phase 0.3–0.5 plan — defect fixes, eval index build, tag

Status: APPROVED 2026-10-13; steps 1–8 done 2026-10-14 (index digest: docs/eval/index-eval-2026-10-v1.md). Follows `docs/evaluation-plan.md` §4
Phase 0 (0.3 defect triage, 0.4 one-off re-ingest, 0.5 tag). Nothing below is
implemented yet.

## 1. What the investigation found (2026-10-13)

The index the September runs used is **local**: Qdrant collection `ragline_pod`
(14,937 points) in the `ragline-qdrant-1` container plus `data/ragline.db`
(119 ready documents, 14,937 chunk records, 57,660 entities, 121,717
relationships; batch of 2026-09-24). The pod only serves the LLM, embedder and
reranker. The indexed chunks for the two defect pages are byte-for-byte what the
parser + chunker produce locally today on pymupdf4llm 1.28.2, so both findings
below hold for the 1.28.2 rebuild as well.

| Q | Recorded verdict | What is actually in the index | Root cause |
|---|---|---|---|
| D10 | "eMT3070A datasheet chunk had only the title and contact details — ingestion looks broken" | Page 1 is indexed in two chunks; chunk 1 (685 chars) carries `Operating Temperature -20° ~ 50°C`. The chunk the model saw ("Source 2") is chunk 3: a **75-character tail** of page 2 (`TEL … Web … eMT3070A1_DataSheet_ENG_20150123`). | Not ingestion. The structural chunker flushes an oversized "sentence" (the page-2 drawing text) and the remainder becomes its own tiny chunk. With its `[Source: emt3070a_7in_datasheet.pdf]` prefix that decoy embeds as "the eMT3070A datasheet", took the one slot the comparison query gave that product, and the spec chunk never reached the top 8. The one-embedding-per-comparison-question limit is the Phase 4 axis and stays out of the freeze. |
| A09 | "table row for 2715-T7CD blank in the chunk" | Tech data p.3: the 6.5/9-inch specification table is split **mid-row** into chunks 4, 5 and 6 by the sentence splitter (it breaks at `6.5-in. \|`, `cat. no. \|`). The `Memory … 512 MB RAM / 250 MB nonvolatile storage` row sits in chunk 5 with **no header row and no catalogue number**; the model saw chunk 4, which stops after "Display size". User manual p.16: the product-selection table's spanning cells (`Yes / 512 MB / 250 MB`) are placed by pymupdf4llm on the 2715-T10CA row only, so every other row reads blank. | Chunker: tables are not treated as units (confirmed defect, fixable). Parser: spanning-cell placement is a pymupdf4llm artefact; filling blanks down is unsafe (blank also means "—"/not applicable), so it is documented as a constant. With the chunker fix the tech-data document alone answers A09 (`source_match: any`). |

Also seen, deliberately **not** in scope (it is identical in the current index, so
it is a constant across all rungs): the layout analyser replaces pymupdf4llm's
markdown with raw reading-order text on pages it classes as multi-column (the
Weintek datasheet page 1 loses its table structure that way). Candidate Phase 4
axis alongside the per-entity retrieval split.

Corpus-wide incidence of the two chunker artefacts (real parser + chunker over
all 119 PDFs, 11,723 pages): *scan running, numbers added before approval.*

## 2. Scope and classification

Medium: `src/ragline/chunking/structural.py` changes affect every document at
ingest time; one campaign-runner preflight; one-off index build with pod spend
(≈ $2–3). Pipeline: this plan → approval → implement → alignment-verifier →
`/code-reviewer` on the diff → commit → index build → tag.

Out of scope: retrieval changes, parser changes, prompt changes, prod index
rebuild (prod keeps `ragline_pod` until the campaign is done).

## 3. Steps

1. **Table-aware chunking** (`structural.py`). Split each page's text into
   blocks first: a *table block* is a run of consecutive markdown rows
   (`|…|` lines, the parser's existing `TABLE_RE` shape); everything else is
   *prose*. Prose goes through the sentence splitter exactly as now. In a table
   block each **row is atomic** (never split inside a row). The *header block*
   is the rows up to and including the `|---|…|` separator when the separator is
   within the first three rows; otherwise the table has no header. A table that
   exceeds the token budget is cut only **between rows**, and every continuation
   chunk is prefixed with the header block (header tokens count against the
   budget; a row that alone exceeds the budget stays whole, as oversized
   sentences do today). No sentence overlap is seeded into or out of a table
   chunk: the repeated header is the overlap. Invariants kept: a chunk never
   spans pages; `char_start` points at the first *row* of the continuation, not
   the repeated header; `chunk_index` stays monotonic.
2. **Tiny tail merge** (`structural.py`, new setting `chunk_min_tokens`, default
   48, with its line comment in `config.py`). After a page's chunks are built, a
   chunk under the minimum that follows a sibling chunk on the same page is
   appended to that sibling (the sibling may exceed the budget by at most
   `chunk_min_tokens`); a tiny *first* chunk of a page is merged into the next
   chunk of the same page; a page that yields only one tiny chunk is left alone.
3. **Tests** (`tests/unit/test_chunking.py`): header repetition on a split table;
   no mid-row cuts; oversized single row kept whole; no overlap into table
   chunks; tiny tail merged backwards and tiny head merged forwards; page and
   `char_start` invariants; plus two regression fixtures taken from the real
   parse — PanelView 5500 tech data p.3 (assert the chunk holding `512 MB RAM`
   also holds `2715-T7CD`) and Weintek eMT3070A p.2 (assert no chunk under 48
   tokens follows a sibling). Line-by-line comments as in the rest of the repo.
4. **Before/after measurement** on the whole corpus with the local parser +
   chunker (the scan script from the investigation): total chunks, chunks that
   start mid-table without a header, mid-row cuts, tiny chunks. Recorded in this
   file under §1 and in the campaign report's reproducibility section.
5. **Campaign guard** (`scripts/eval_campaign.py`, `eval/campaign/eval-2026-10.toml`):
   the campaign file gains `[index]` with `collection = "ragline_eval_v1"` and
   `database_url = "sqlite+aiosqlite:///./data/ragline_eval_v1.db"` (shape
   validated). The runner pins both into the environment of every
   `evaluate.py` / `eval_load.py` process (process env outranks `.env`), so no
   rung can read the dev/prod index and `.env` is never edited for it. Preflight
   refuses to spend (exit 5) when the collection is missing or empty, when its
   point count differs from `[index].points` once that is recorded after the
   build, or when the DB file is missing. `evaluate.py` already writes the
   collection and point count into every manifest. Tests in
   `test_eval_campaign.py`.
   *Amended during implementation (2026-10-13): the draft said "refuse when the
   resolved collection differs", which would have required editing `.env` and
   so repointing the dev stack; pinning per process does the same job without
   that side effect.*
6. **Eval index build** (plan 0.4; after 1–5 are committed). No `.env` edit:
   the three settings are passed as environment overrides for the ingest
   process only, which pydantic-settings ranks above `.env` —
   `QDRANT_COLLECTION=ragline_eval_v1`,
   `DATABASE_URL=sqlite+aiosqlite:///./data/ragline_eval_v1.db`,
   `UPLOAD_DIR=./data/uploads_eval_v1`. Fresh DB ⇒ no duplicate-skipping, fresh
   knowledge graph. Pod: podlink profile `eval-r3-qwen3-30b-a3b-2507-awq`
   (the prod `Qwen3-30B-A3B-Instruct-2507-AWQ`, lifecycle terminate), so the
   KG extractor is one fixed model and the pod is a ladder pod. Ingest root: a
   staging directory whose only child is `hmi/` (hard-linked from
   `testdata/hmi`), so `source_path` keeps the `hmi/vendor/…` prefix the golden
   set uses, as the prod index does. Command:
   `python scripts/ingest.py <staging> --original-base <same base as prod>`.
   Expect ≈ 1 h on the PRO 6000 (119 docs / 11,723 pages, KG extraction is the
   long pole). Spend ledgered as `r0-index` in `eval/results/eval-2026-10/spend.jsonl`.
7. **Index digest + smoke**, same pod session: record document / chunk /
   entity / relationship counts, parser version, chunker settings and the
   collection name in `docs/eval/index-eval-2026-10-v1.md`; confirm by direct
   Qdrant scroll that the A09 memory row now shares a chunk with `2715-T7CD` and
   that the eMT3070A datasheet has no sub-48-token chunk; then one unofficial
   pass of `scripts/evaluate.py eval/golden_set_hmi.json --path rag` with the
   eval overrides (≈ 10 min, ≈ $0.40) to check the index serves retrieval end to
   end before the pod is terminated. Not a ladder result (rung 3 OFF runs
   officially later).
8. **Tag** `eval-2026-10-v1` on the commit that contains 1–5 and the digest
   (plan 0.5); update `docs/evaluation-plan.md` §2 (index row, defect row) and
   the Phase 0 progress; update the memory file.

## 4. Acceptance

- A09: the chunk containing `512 MB RAM` on tech-data p.3 also contains the
  header row with `2715-T7CD` (unit regression + Qdrant check after build).
- D10: no chunk of `emt3070a_7in_datasheet.pdf` under 48 tokens; the page-1
  spec chunk is unchanged in content.
- Unit suite green, ruff clean; corpus chunk count change reported (§1).
- New collection `ragline_eval_v1` with 119 ready documents; digest file
  committed; campaign preflight refuses any other collection.

## 5. Risks

- Header repetition raises token count and chunk count a little for long
  tables; measured in step 4 and reported.
- A changed chunker changes **every** chunk id, so the eval index is not
  comparable chunk-for-chunk with `ragline_pod`; comparisons are at question
  level, as planned.
- Fixing A09/D10 at the chunk level does not guarantee the retriever ranks the
  fixed chunk; the step-7 smoke shows whether it does before any ladder spend.

## 6. Build log and deviations (2026-10-13)

- **Attempt 1** (profile `eval-r3-qwen3-30b-a3b-2507-awq`, $2.49/h, ≈ $1.46,
  ledgered as `r0-index`): stopped after ≈ 10 min of ingest. Findings:
  1. KG extraction output hit `KG_EXTRACTION_MAX_TOKENS=2048` on 27 of 76
     calls; truncated JSON is discarded, so those chunks got no graph. Raised
     to **4096** for the build (an existing setting, passed as a process
     override): truncation fell to ≈ 18% of calls, the remainder being dense
     table chunks whose output runs past 4096. Documented as a constant of the
     eval index.
  2. The rung profile's handoff sets `KG_EXTRACTION_CONCURRENCY=2` and vLLM
     `--max-num-seqs 8` (sized for the throughput probe), giving ≈ 11, then
     ≈ 30 extraction calls/min — 8–23 h for ≈ 15k chunks.
  3. Parallel workers raced to create the new Qdrant collection (one 409,
     one document failed). The collection is now created once before the
     ingest with the prod collection's settings (4096-d, cosine). The race in
     `QdrantVectorStore._ensure_collection` is a ragline bug left for later.
- **Attempt 2** uses a dedicated profile `eval-r0-index-build` (same image,
  same `stelterlab/Qwen3-30B-A3B-Instruct-2507-AWQ` extractor, `--max-num-seqs
  32`, `KG_EXTRACTION_CONCURRENCY=32`, fallback to any Secure PRO 6000 data
  centre). The extractor model is unchanged, so the index is what step 6
  specifies; only ingest throughput differs.
- Ingest overrides used: `QDRANT_COLLECTION=ragline_eval_v1`,
  `DATABASE_URL=sqlite+aiosqlite:///./data/ragline_eval_v1.db`,
  `UPLOAD_DIR=./data/uploads_eval_v1`, `BATCH_MAX_PARALLEL=6`,
  `KG_EXTRACTION_MAX_TOKENS=4096`; concurrency from the profile handoff.
- **Attempt 2 outcome** (≈ $4.60, ledgered): stopped by the user at 16:10 with
  50 of 119 documents complete. Extraction ran at 130–250 calls/min with
  ≈ 4.5% of calls still cut off at 4096 tokens and no document failures, but
  the build was parse-bound: thread-pool parsing of the large Mitsubishi
  GOT2000 manuals left the pod waiting. Partial index kept for resumption: the
  69 incomplete documents' vectors and rows were removed, leaving 50 complete
  documents, 7,968 chunks (Qdrant and chunk records agree), 41,336 entities,
  100,258 relationships. The 69 remaining files are being pre-parsed on the
  CPU (`docs/eval/parse-cache-plan.md`); the build resumes on the pod from the
  parse cache once that plan is approved and implemented.
- **Note for the campaign:** until the build is complete and `[index].points`
  is recorded in `eval/campaign/eval-2026-10.toml`, the preflight only checks
  that `ragline_eval_v1` is non-empty, which the partial index is. No rung may
  run before the index is complete.
- **Attempt 3** (2026-10-14, profile `eval-r0-index-build` with the any-data-centre
  rung first because the weights volume's data centre returned a non-retryable
  create error; $3.67 incl. the smoke pass): the 69 remaining documents were
  ingested from the parse cache in 52 min with no parsing, 0 failures. Index
  complete: 119 documents, 15,064 chunks. Checks pass; `[index].points =
  15064` recorded in the campaign file. Total build cost $9.73.
