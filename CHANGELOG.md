# Changelog

All notable changes to ragline are documented here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com); versions follow SemVer.

## [0.1.0] — 2026-10-05

First public release. ragline was developed privately before this; the
history starts here.

### Pipeline
- Batch ingestion (files, ZIP, server-side folder, CLI) for PDF, DOCX and
  XLSX, with layout analysis, optional OCR fallback, SHA-256 deduplication and
  document versioning.
- Hybrid retrieval: dense (Qdrant) + BM25, Reciprocal Rank Fusion,
  cross-encoder rerank, lost-in-the-middle reordering, optional restriction to
  selected documents.
- Knowledge-graph extraction at ingest and graph context at answer time.
- Programmatic citations: the model emits markers only; source identity,
  page and quote come from the retrieved chunks.
- Chat with a structured pre-pass, session memory, a per-turn memory toggle,
  a confidence score, answer-length control and library-mode answers from
  metadata.
- Chat and Documents UI (React): folder explorer, user folders, retrieval
  scope selection, citation sidebar with page-anchored links.

### Model endpoints
- One OpenAI-compatible LLM endpoint and one embedding endpoint, set by
  environment variables; query-instruction support for Qwen3-Embedding.
- Reranker as a local CPU cross-encoder, a TEI `/rerank` endpoint or a
  Cohere-style `/v1/rerank` endpoint.
- `scripts/apply_pod_env.py`: the receiving end of podlink's client-env
  handoff — merges a pod's live endpoints into `.env` and restarts.

### Evaluation
- 60-question HMI golden set with expected sources, pages and quoted
  evidence, and its review sheet.
- `scripts/evaluate.py`: per-question source hit, citation, page sanity,
  latency, tokens and per-stage timings, with the stack recorded per run.
- Four recorded runs on one stack across two GPUs, and a hand-graded
  analysis.
- Corpus index (`eval/corpus/`) for the 803 documents the corpus contains,
  with `scripts/build_corpus_index.py` and `scripts/fetch_corpus.py`.

### Dependencies
- PDF parsing pinned to `pymupdf4llm` 1.28.2 (with matching PyMuPDF and
  pymupdf-layout): the first version in which the whole parser stack is
  AGPL-3.0 rather than partly noncommercial-only, and in which threaded
  parsing is deterministic. The recorded runs were ingested with 1.28.0.

### Defaults
- `env.template` starts a local single-user instance as copied; `restart.sh`
  binds `127.0.0.1`.

### Experimental
- Entra ID sign-in, per-user sessions and NTFS-ACL gating of citation links,
  with systemd, nginx and backup units (`deploy/intranet/`). Implemented and
  unit-tested; not validated in a real deployment.
