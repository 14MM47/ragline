## What & why

<!-- What does this change, and why? Link any related issue. -->

## How tested

<!-- ruff + unit tests + frontend checks, plus anything live (an ingest, a golden-set run?). -->

## Checklist

- [ ] `ruff check .` is clean and `pytest tests/unit` passes
- [ ] Frontend: `npx tsc --noEmit`, `npm test` and `npm run build` pass (if touched)
- [ ] New settings are in both `config.py` and `env.template`
- [ ] No documents, keys, bearers or pod ids committed
- [ ] If retrieval or answering changed: before/after golden-set results attached
- [ ] Docs/README updated if behaviour or config changed
