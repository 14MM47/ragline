# Contributing to ragline

Thanks for your interest. ragline is a proof-of-concept test bench for RAG on
rented GPUs; contributions that make it a better instrument — more accurate
measurement, clearer failure analysis, fewer things to trip over when wiring a
new stack — are very welcome.

## Dev setup

```bash
git clone https://github.com/14MM47/ragline && cd ragline
uv sync --extra dev --extra ocr
(cd frontend && npm ci)
```

You do **not** need a GPU, a model endpoint or Qdrant to develop or run the
unit tests — they stub the model clients and never make live calls.

## Running the checks

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest tests/unit -q
(cd frontend && npx tsc --noEmit && npm test && npm run build)
```

CI runs exactly these on every push and pull request.

The integration test (`RAGLINE_INTEGRATION=1 pytest tests/integration`) and
the evaluation scripts need a running Qdrant and configured endpoints; run
them when a change touches the pipeline.

## Guidelines

- **Keep the pipeline comparable.** The point of the project is that the
  retrieval and answer path stays fixed while models change. A change that
  alters what is retrieved or how an answer is built should say so, and
  should come with a before/after golden-set run (see
  [docs/evaluation.md](docs/evaluation.md)).
- **Everything deployment-specific is a setting.** No endpoints, model names,
  paths or account details in code. A new setting goes in
  `src/ragline/config.py` *and* `env.template`, with a comment saying what it
  does — the two are kept one to one.
- **No documents in the repository.** The corpus is indexed in `eval/corpus/`,
  not included. Do not commit PDFs, and do not commit `.env`, `data/` or
  anything containing a key, a bearer or a pod id.
- **Preserve the safe defaults:** loopback bind, the auth interlock, the
  `INGEST_ROOTS` allowlist.
- **Match the house style:** every module opens with a docstring explaining
  its role, and the code is commented line by line — why, not what. `ruff
  check` clean (the formatter is deliberately not enforced: it would undo the
  aligned comments). Tests for new behaviour.
- **Golden-set changes** go through the review sheet
  (`eval/golden_set_hmi_review.md`): an expected answer is only as good as the
  page it was checked against.

## Preparing a public release

The maintainer [publishing runbook](docs/publishing.md) covers exporting a
reviewed tree into fresh Git history, checking the staged repository, and
enabling the security reporting channel.

## Pull requests

Open an issue first for anything non-trivial. Keep PRs focused, describe the
change and how you tested it, and make sure CI is green. By contributing you
agree your work is licensed under the project's MIT licence.
