# Parse cache — parse in advance, ingest from the cache

Status: APPROVED and implemented 2026-10-13 (steps 1–5). Small/Medium (one new module, one
worker hook, one script, one setting, tests).

## Why

The eval index build on 2026-10-13 was parse-bound: parsing runs locally in a
thread pool where pymupdf4llm's layout engine holds the GIL, so about two
cores do the work, and the pod (embedder + KG extractor) sat idle for long
stretches while large manuals parsed (six Mitsubishi GOT2000 manuals ≈ 17 min
each). Two pod sessions cost $6.06 for 50 of 119 documents. Parsing needs no
GPU; doing it beforehand, in separate processes, leaves the pod only
embedding and KG extraction. At 1 TB the same split is what makes parsing
days rather than months (any number of CPU processes or machines).

## Steps

1. **`src/ragline/parsing/cache.py`** — a content-addressed cache of
   `ParsedDocument`s. Key: SHA-256 of the file bytes. Namespace: a
   fingerprint = first 12 hex of SHA-256 over
   `{"format": 1, "pymupdf4llm": <ver>, "pymupdf": <ver>,
   "enable_ocr_fallback": <bool>, "enable_layout_analysis": <bool>}` — any
   parser or parser-setting change misses the cache instead of serving stale
   output. File: `<PARSE_CACHE_DIR>/<fingerprint>/<sha256>.json.gz`, the
   dataclass as JSON (`dataclasses.asdict`), written atomically (temp file +
   rename). `get(path_bytes) -> ParsedDocument | None`, `put(...)`.
2. **Setting `PARSE_CACHE_DIR`** (default empty = cache off, behaviour
   unchanged), line comment in `config.py`, `env.template`,
   `docs/configuration.md`.
3. **Worker hook** (`ingestion/worker.py` `_parse_document`): when the cache
   is on, look up by the bytes' hash first; on a miss parse as today and
   store. Chunking still runs at ingest (fast, and it is the part that
   changed today).
4. **`scripts/preparse.py <root> [--workers N]`** — walks the root like
   `ingest.py`, parses every supported file into the cache with a
   **process** pool (default cores − 1), skips files already cached, prints
   done/total, rate and ETA. Needs no pod, no Qdrant, no DB.
5. **Tests**: round-trip a ParsedDocument; fingerprint changes with parser
   version and settings; worker uses a hit and stores a miss; corrupt cache
   file falls back to a parse; preparse skips cached files (parser stubbed).

## Resuming the eval build with it

The partial eval index keeps the 50 complete documents (7,968 chunks, 41,336
entities); the 69 incomplete ones were removed from Qdrant and the DB
(backup of the DB taken first). After 1–5: pre-parse the 69 remaining files
(already started 2026-10-13 with a stand-alone script writing this exact
layout, `data/parse_cache/`), then ingest only those 69 from a staging root
holding just them, on the `eval-r0-index-build` pod with
`PARSE_CACHE_DIR=./data/parse_cache`. Expected pod time ≈ 1 h for the
remaining ≈ 7,500 chunks (embedding + KG at ≈ 130–250 calls/min).

## Implementation notes (2026-10-13)

- After the code review the fingerprint also covers the OCR engine actually
  installed (Tesseract version or "absent"), a hash of ragline's parsing
  source, and the python-docx / openpyxl / pandas versions. The 69
  stand-alone entries (made on this host, same settings, parsing code
  unchanged since 2026-10-06) were moved into the new namespace
  `d8a50c5d1dd0` after checking the old identity is a subset of the new. On a real-data check, cached and fresh parses are
  identical and chunk identically.
- `get()` takes the current file name and overrides the stored one: identical
  bytes uploaded under another name must cite that name.
- Cache write failures are logged, never fail a document; unreadable entries
  are a miss and get re-parsed and overwritten.
- Temp files are unique per writer (threads share a pid); any cache write
  error is logged and never fails a document; `preparse.py` refuses to run
  with OCR enabled but no Tesseract unless `--allow-no-ocr` is given.
