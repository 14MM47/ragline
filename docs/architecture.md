# Architecture

ragline is one FastAPI process, one Qdrant container, a SQLite file, and a
built React app served by the same process. Every model call leaves the
machine through one of three clients — LLM, embedder, reranker — each
configured by a base URL, a key and a model name. That boundary is the point
of the project: the pipeline is held still so the models behind it can be
swapped and compared.

## The three endpoints

| Client | Code | Calls | Configured by |
|---|---|---|---|
| LLM | `llm/openai_provider.py` | answers, entity extraction, chat pre-pass, memory post-pass, confidence | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` |
| Embedder | `embeddings/openai_embedder.py` | chunks, queries, graph entities | `EMBEDDING_*` (falls back to the `LLM_*` values when empty) |
| Reranker | `retrieval/reranker.py` | candidate reordering | `RERANKER_PROVIDER` = `local` (CPU cross-encoder in-process), `api` (TEI or Cohere-style endpoint), or `none` |

The LLM and embedder use the plain `openai` SDK against a configurable base
URL, so OpenAI, Azure OpenAI, vLLM and TEI all look the same to the rest of
the code. The reranker is separate because the OpenAI API has no rerank
operation.

Token usage is collected inside the LLM provider by a context-local trace
collector (`tracing/`), so every route gets whole-turn prompt and completion
totals, and per-stage timings, without threading counters through the call
stack.

## Ingestion

`ingestion/worker.py` processes a batch of documents, `BATCH_MAX_PARALLEL` at
a time:

1. **Deduplicate** by SHA-256 — an identical file already ingested is skipped
   before any parsing.
2. **Parse** (`parsing/`): PDFs through pymupdf4llm to per-page Markdown, with
   a layout analyser that strips repeated headers and footers and handles
   two-column pages, and an optional Tesseract fallback for pages with almost
   no extractable text. DOCX and XLSX have their own parsers.
3. **Chunk** (`chunking/structural.py`): token-budgeted (512 by default),
   split on sentence boundaries, with overlap, and never across a page — each
   chunk knows the exact page it came from.
4. **Embed and store**: one dense vector per chunk in Qdrant, with the full
   source payload (file, page, section, offsets); chunk text and metadata in
   SQLite.
5. **Extract a knowledge graph** (`knowledge_graph/`, optional): one LLM call
   per chunk yields entities and relationships, stored in SQLite with the
   document and chunk they came from.
6. **Rebuild BM25** once the batch finishes. A chunk is findable by vector as
   soon as it is stored, and by keyword after its batch completes.

Documents arrive by browser upload (files or a ZIP), by naming a folder under
an allowlisted server path (`INGEST_ROOTS`), or from `scripts/ingest.py`.
Uploading a new version of a document supersedes the old one.

## Retrieval

`retrieval/pipeline.py` is the single path every query takes:

1. Embed the query (with an instruction prefix for embedders that want one).
2. **Dense** search in Qdrant and **sparse** BM25 search, `RETRIEVAL_TOP_K`
   candidates each.
3. **Reciprocal Rank Fusion** merges the two lists (`retrieval/hybrid.py`).
4. **Rerank** the fused candidates down to `RERANK_TOP_K`. When the dense
   scores already show a clear winner that fusion also ranked first, the
   reranker is skipped.
5. **Reorder** so the strongest chunks sit at the start and end of the prompt
   (`retrieval/reorder.py`).

A query can be restricted to a set of document ids — the Documents tab's
selection — in which case both searches are filtered and an empty
intersection searches nothing rather than widening.

## Answering and citations

`agent/rag_agent.py` builds the prompt from the reranked chunks as numbered
`[Source N]` blocks, adds a knowledge-graph subgraph limited to the documents
those chunks came from, and asks the LLM to answer using only the numbered
sources.

The model is trusted with the *marker* and nothing else
(`citations/postprocessor.py`):

- every source's identity — file, page, section, quote, document id — comes
  from the retrieved chunk, never from generated text;
- a marker that points outside the list is dropped;
- repeated citations of the same file and page collapse;
- a token-overlap check realigns answers whose source numbering is
  systematically shifted.

Each surviving citation links to the stored copy of the document at the cited
page. If the file's original location was recorded at upload
(`storage/paths.py`), the citation shows that too.

## Chat

`chat/chat_agent.py` wraps the answer path in up to four passes:

1. **Pre-pass** — one structured LLM call rewrites the question to stand
   alone and routes it: retrieval, library, or both.
2. **Answer** — the RAG path above; or **library mode**, which answers
   questions about the collection itself from the metadata database with no
   vector search; or the two combined.
3. **Memory post-pass** — updates the session's running summary, topics and
   key facts.
4. **Confidence** — one cheap LLM call scoring how well the answer addressed
   the question.

The answer is streamed to the browser before passes 3 and 4 run. Session
memory is one JSON file per session under `data/memory/`.

Each turn has a **memory toggle**. Off, the question is answered alone — no
pre-pass, no conversation context, no post-passes — and the token count drops
accordingly. On, the prompt carries the prior conversation, including turns
that were themselves taken with memory off.

## Storage

| What | Where |
|---|---|
| Chunk vectors + source payload | Qdrant collection (`QDRANT_COLLECTION`) |
| Documents, batches, chunk text, graph entities and relationships, query traces, folder layout | SQLite (`data/ragline.db`) |
| Uploaded files | `data/uploads/` |
| Chat sessions | `data/memory/` |

Tables are created on startup (`storage/metadata_db.py`); there is no
migration framework yet, only a few in-place column additions.

## HTTP API

All under `/api`.

| Area | Routes |
|---|---|
| Health | `GET /health` |
| Documents | `GET /documents`, `GET /documents/explorer`, `POST /documents/upload`, `GET /documents/{id}/content`, `DELETE /documents/{id}`, `POST /documents/{id}/retry`, `POST /documents/{id}/new-version`, `GET /documents/{id}/versions` |
| Folder layout | `GET /documents/layout`, `POST`/`DELETE /documents/layout/folders`, `PUT`/`DELETE /documents/layout/placements/{id}` |
| Batches | `POST /batches/upload`, `POST /batches/ingest-path`, `GET /batches`, `GET /batches/{id}` |
| Query | `POST /query` (one-shot, no session) |
| Chat | `POST /chat` (server-sent events), `GET /sessions`, `GET`/`DELETE /sessions/{id}`, `POST /sessions/{id}/compact`, `POST /sessions/{id}/clear-memory` |
| Auth (experimental) | `GET /auth/login`, `GET /auth/callback`, `POST /auth/logout`, `GET /auth/me`, `GET /admin/acl-status`, `POST /admin/users/{oid}/revoke-sessions` |

FastAPI's interactive documentation is at `/docs` on a running instance.

## Module map

| Package (`src/ragline/…`) | Role |
|---|---|
| `api/` | Routers, request/response schemas, dependency wiring, the document explorer |
| `ingestion/` | The batch worker |
| `parsing/` | PDF, DOCX and XLSX parsers, layout analysis, the extension registry |
| `chunking/` | Token-budgeted, page-exact chunking |
| `embeddings/` | The OpenAI-compatible embedder |
| `vectorstore/` | Qdrant storage and search |
| `retrieval/` | Hybrid search, fusion, reranking, reordering |
| `knowledge_graph/` | Entity/relationship extraction, storage, the in-memory graph index |
| `agent/` | The RAG answer path and its prompts |
| `citations/` | Marker extraction, verification, formatting |
| `chat/` | Sessions, memory, the pre-pass, routing, the multi-pass turn |
| `llm/` | The single OpenAI-compatible LLM provider |
| `storage/` | SQLite models, the file store, original-path handling |
| `tracing/` | Per-query token and latency accounting |
| `auth/`, `acl/` | **Experimental.** Entra ID sign-in and per-user gating of citation links by NTFS ACL — see below |

## The experimental multi-user layer

`auth/` and `acl/` implement a design for running ragline for several people
on an intranet: Entra ID sign-in through a backend-for-frontend OIDC flow,
per-user chat sessions, and a crawler that reads each source file's NTFS
permissions over SMB so that a citation's link and download are only offered
to users who could open the original. It is unit-tested, and it has not been
run against a real tenant or file server.

With `AUTH_ENABLED=false` — the configuration `env.template` ships and the
only one this project is tested in — none of it is active: every request runs
as a single local user. [deploy/intranet/RUNBOOK.md](../deploy/intranet/RUNBOOK.md)
records the design; [SECURITY.md](../SECURITY.md) says what that means for
where ragline can safely run.
