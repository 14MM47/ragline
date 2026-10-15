# Plan — fixing ragline's own faults found by rung 2 (before rung 3)

Status: APPROVED 2026-10-15; stage 1 implemented on `feature/stage1-query` (code review APPROVE, architect APPROVE_WITH_CHANGES applied, alignment ALIGNED), verification run `r2-s1` pending. **Large** (retrieval, ingestion,
prompts, evaluation tooling; re-ingest into a new frozen index). Per the user's
direction: rung 2 is ragline's initial-state test; clear every model-independent
fault we can, verify on the failing questions plus controls, then run rungs 3–6
on the fixed ragline and repeat rung 2 at the end for a direct comparison.

## What rung 2 showed

35 of 100 questions were not fully correct in all six passes (3 thinking-OFF,
3 thinking-ON). Each was traced (evidence quote → indexed chunk → rank in
retrieval → what the model saw → answer → judge reason) and diagnosed by hand
against the chunk text, in four groups; diagnoses in the session scratchpad
(`r2_diag_part1..4.json`), to be committed as `eval/results/eval-2026-10/r2/diagnosis.json`.

| | Questions |
|---|---|
| Root cause fixable in ragline | 35 of 35 |
| Fix would help any model (model-independent) | 31 |
| Evidence never reached the model | 22 |
| Evidence reached it only sometimes | 4 |
| Evidence always in front of the model | 9 |

Primary causes: comparison retrieval brings only one side (10), answer
style/prompt (5), chunking lost context (4), evidence chunk not retrieved (4),
parsing damaged the evidence (3), model misread (3), query rewrite changed the
question (2), reranked out (2), misleading sibling chunk (1), judge (1).

Confirmed in the code (not just inferred from answers):

1. **No document context in the index.** `Chunk.context_prefix`
   (`chunking/models.py`) is never called; `ingestion/worker.py:180` embeds bare
   `c.text`, BM25 (`retrieval/hybrid.py:56`) and the reranker
   (`retrieval/reranker.py:129`) also see bare text. A table continuation or a
   spec chunk that never names its product cannot be found by product name.
2. **BM25 tokenises on whitespace** (`hybrid.py:56,71`, `lower().split()`):
   markdown table cells fuse with pipes, `**` and `<br>` into unmatchable
   tokens; catalogue numbers carry trailing commas. Replayed offline: C11's
   Delta and Omron evidence chunks score exactly 0 today and rank #2–#7 with a
   regex tokeniser plus per-entity queries. ~27 % of chunks are tables.
3. **The answer model never sees the user's question.** `chat/chat_agent.py:195`
   passes the pre-pass keyword rewrite into `RAGAgent.query`, which fills the
   prompt's `Question:` slot — "Which is higher, X or Y?" arrives as
   "X vs Y max temp", so winners, steps and comparisons get dropped (A10, H03,
   D12, F03). Prompt rule 7 ("avoid repeating information") adds to it.
4. **One retrieval per comparison.** One entity or one manual fills the top-8
   (G04: all eight slots from one manual; B15: six of eight).
5. **Parsing loses merged table cells** (a spec spanning two models is left
   blank for one, D07, G02, A12) and, where the layout analyser replaces a page,
   **scrambles multi-column tables** (A11, F02, C12: values cut off from their
   model headers).
6. **Page-bounded chunks orphan procedure steps and table continuations**
   (H01, H07, B12, B15); footer/boilerplate chunks take top-8 slots (A09, H01, C11).
7. **The judge is inconsistent** in places: identical answers graded
   differently (G07, A10, E04, E10, G06) — an evaluation-tooling fault that
   blurs model comparisons.
8. Correction to the earlier summary: at document level the right document was
   usually retrieved, but at chunk level the evidence chunk usually was not —
   the dominant fault is chunk-level retrieval, not answering.

## Fixes

Grouped by where they live; query-time fixes need no re-ingest, so they are
built and verified first, on the current index, to attribute the gains.

### Stage 1 — query time (index v1 unchanged)

1. **BM25 tokeniser**: strip markdown/HTML, split on non-alphanumerics, keep
   hyphen/dot/slash-joined identifiers (`2711p-t7c21d8s`, `dop-107wv`) as whole
   tokens as well as their parts; lowercase; tests on real table rows.
2. **Question and query separated**: the pre-pass returns a natural-language
   standalone question (follow-ups resolved) *and* the search query; retrieval
   uses the query, the answer prompt gets the question. Pre-pass prompt: keep
   the question's intent words ("which", "cannot", "compare", "steps").
3. **Per-entity retrieval for comparisons and multi-entity questions**: the
   pre-pass lists the named products/catalogue numbers; one retrieval per
   entity, merged with reserved top-8 slots per entity and a per-document cap.
4. **Neighbour expansion**: for the reranked hits, add the next (and previous)
   chunk of the same document when it continues a table or numbered list, within
   the context budget — recovers orphaned rows and steps without changing the
   page-exact citation rule.
5. **Rerank pool and dedupe**: rerank the full fused pool (record it), drop
   near-duplicate and footer/boilerplate chunks (repeated short text), and
   evaluate a final context of 8 vs 10.
6. **Answer prompt**: answer every part; give values with units; for
   comparisons give both values and name the winner; for how-to questions give
   all numbered steps; never substitute a sibling model's value — say it is
   not stated; conversation context is background, answer the current question.
   Rule 7 softened accordingly.

### Stage 2 — ingest time (re-ingest into `ragline_eval_v2`)

7. **Chunk context**: prefix every chunk's indexed text (embedding, BM25,
   rerank) with document title, product/catalogue identifiers derived from the
   document (title page + filename) and the section path; the stored citation
   text stays the original.
8. **Section headings carried across pages** (last heading, not the first
   heading of the page; none = inherited).
9. **Tables**: forward-fill merged/spanning cells into every row they span;
   repeat the header for plain-text tables too; do not let the layout analyser
   replace a page that has markdown tables; rejoin catalogue numbers broken
   across lines.
10. **Boilerplate**: footer-only chunks dropped at ingest (keeps them out of the
    index rather than filtering at query time).
11. Re-ingest with the parse cache (parser changes invalidate it: one full
    local re-parse, CPU only, then ≈ 1.5 h of pod for embedding + KG).

### Stage 3 — evaluation tooling

12. **Judge consistency**: identical answer text for a question gets one verdict
    (graded once, reused across passes and conditions); rubric clarified for
    labelled sibling values on unanswerable questions; the GPT second-opinion
    sample run on rung 2 as planned.
13. **Golden fixes for your review**: G04 (evidence chunk is the wrong model
    table), E10 (corpus also has TP1500 Basic and IFP1500 Basic), D12 / H05
    (ambiguous wording) — each listed with the evidence; nothing changes
    without your OK.
14. **Harness**: `--ids` / subset file for targeted runs (recorded in the
    manifest); the failure dossier and diagnosis tooling moved into
    `scripts/eval_failures.py` for every later rung; retrieval records the full
    reranked pool, not just the top-20.

## Verification (your requirement)

After each stage: pod up, **3 passes thinking OFF + 3 thinking ON** on the
questions attributed to ragline faults (all 35) **plus 15 control questions**
that rung 2 got fully correct (stratified by category) to catch regressions;
judged the same way; a before/after table per question and per fix group.

| Run | Index | Questions | Pod time | Cost |
|---|---|---|---|---|
| Verify stage 1 | v1 | 50 | ≈ 1.5 h | ≈ $4 |
| Re-ingest | v2 | — | ≈ 1.5 h | ≈ $4 |
| Verify stage 2 | v2 | 50 | ≈ 1.5 h | ≈ $4 |

Then the campaign resumes on index v2 and the fixed ragline (rungs 3–6), and
rung 2 is repeated in full at the end. The rung 2 results recorded so far stay
as the initial-state baseline. Total ≈ $12 plus judging; campaign spend today $35.29.

## Pipeline

Large task: implementation in feature branches per stage, tests first for the
tokeniser, entity split and table forward-fill; `/code-reviewer` on each stage
and an architecture check (`/architect`) on stages 1–2 since they change the
retrieval path and the ingest contract.
