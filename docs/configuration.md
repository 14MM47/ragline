# Configuration

All configuration is environment variables, read from `.env` in the repo root.
[`env.template`](../env.template) is the complete reference — every setting,
its default, and what it does — and maps one to one onto
[`src/ragline/config.py`](../src/ragline/config.py). This page is the short
version: what you have to set, what you might want to, and what bites.

```bash
cp env.template .env
```

As copied, the file starts a local single-user instance with auth off. The
only values it cannot supply are your model endpoints.

`.env` is strict: a key that is not a ragline setting stops the app at startup
with a validation error. That catches typos; it also means a `.env` written
for an older version can need a line removed.

## Model endpoints

| Setting | Meaning |
|---|---|
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | The OpenAI-compatible endpoint for every LLM call. For vLLM, `LLM_MODEL` is the served model name. |
| `EMBEDDING_BASE_URL`, `EMBEDDING_API_KEY` | Leave empty to reuse the LLM values (one cloud endpoint serves both). Set them when the embedder is a separate server. |
| `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | The embedding model and, for servers that need it stated, its output dimension. |
| `EMBEDDING_QUERY_INSTRUCTION` | For instruction-tuned embedders (Qwen3-Embedding): text prepended to queries, not documents. Empty for others. |
| `RERANKER_PROVIDER` | `local` — CPU cross-encoder in the app process (`RERANKER_MODEL`, ~2 GB download on first start). `api` — a remote endpoint. `none` — no reranking. |
| `RERANKER_BASE_URL`, `RERANKER_API_KEY`, `RERANKER_API_FORMAT` | For `api`: the server root, its key, and `tei` (`POST /rerank`) or `cohere` (`POST /v1/rerank`, as vLLM serves it). |

Worked examples for a cloud API and for a GPU pod are in the
[README](../README.md#quickstart-local-single-user) and
[gpu-pod.md](gpu-pod.md).

## The trap: embedder and collection go together

A Qdrant collection holds vectors from one embedding model. Change
`EMBEDDING_MODEL` (or its dimension) and the existing collection is unusable
with it. Select a new `QDRANT_COLLECTION`, `DATABASE_URL`, `UPLOAD_DIR` and
`MEMORY_DIR`, then ingest again. Keeping the old SQLite database would skip
duplicate documents even though the new collection is empty, and reuse graph
embeddings from the old model. Keep each experiment's storage together so you
can switch back. The [GPU pod guide](gpu-pod.md#changing-the-embedder-means-re-ingesting)
has a complete example.

## Settings worth knowing

| Setting | Default | Why you would change it |
|---|---|---|
| `QDRANT_COLLECTION` | `ragline` | One per embedder, as above. |
| `ENABLE_KNOWLEDGE_GRAPH` | `true` | Off makes ingestion much cheaper (no LLM call per chunk) and removes the graph stage from every query. |
| `KG_EXTRACTION_CONCURRENCY` | `20` | Lower it so an ingest leaves the LLM responsive for chat; raise it on a card with headroom. |
| `BATCH_MAX_PARALLEL` | `3` | Documents parsed at once. Parsing is CPU-bound; raise towards your core count. |
| `RETRIEVAL_TOP_K` / `RERANK_TOP_K` | `20` / `8` | Candidates fetched per search leg, and chunks that reach the prompt. |
| `CHUNK_MAX_TOKENS` | `512` | Changing it only affects documents ingested afterwards. |
| `ENABLE_OCR_FALLBACK` | `true` | Needs the `ocr` extra and the `tesseract` binary; without them the fallback is skipped and scanned pages yield no text. |
| `USE_STRUCTURED_PREPASS`, `ENABLE_CONFIDENCE` | `true` | Each is one extra LLM call per chat turn. |
| `INGEST_ROOTS` | empty | `;`-separated directories the "Ingest server folder" panel may read. Empty disables it. |
| `LOG_LEVEL` | `info` | `debug` logs each embedding and rerank call. |

Storage paths (`DATABASE_URL`, `UPLOAD_DIR`, `MEMORY_DIR`, `FRONTEND_DIST`)
default to `./data/` and `frontend/dist`, relative to where the app is
started. `restart.sh` always starts it from the repo root.

## Auth settings

`env.template` ships:

```dotenv
AUTH_ENABLED=false
RAGLINE_ALLOW_INSECURE_DEV=1
```

Both are needed. With auth off, the app refuses to start unless the second
line is present — a deliberate interlock, so that an instance meant to have
sign-in can never come up without it because of one mistyped value. Together
they mean: no login, one local user with full rights. That is safe only while
the port is not reachable by anyone else, which is why `restart.sh` binds
`127.0.0.1` (override with `HOST=…` if you understand the consequence).

The `ENTRA_*`, `SESSION_*`, `SMB_*` and `ACL_*` settings belong to the
experimental multi-user mode and are ignored with auth off. See
[deploy/intranet/RUNBOOK.md](../deploy/intranet/RUNBOOK.md) and
[SECURITY.md](../SECURITY.md).

## Applying changes

Settings are read once at startup, and the model clients are built then.
After editing `.env`, restart: `./restart.sh`.
