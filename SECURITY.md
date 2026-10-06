# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** — do not open a public issue.

Use GitHub's **[Report a vulnerability](https://github.com/14MM47/ragline/security/advisories/new)**
(Security → Advisories) to open a private advisory. You'll get an
acknowledgement, and a fix or mitigation will be coordinated before any public
disclosure.

## What ragline is, and is not

ragline is a **proof-of-concept that runs for one person on their own
machine**. That is the only configuration it is developed and tested in, and
its defaults assume it:

- `restart.sh` binds the API and UI to `127.0.0.1`. Qdrant is published on
  loopback only.
- `env.template` ships with **authentication off**. Every request is then
  treated as one local user who can read every document, delete documents and
  call the admin routes. There is no login.

**Do not expose the port.** Binding ragline to a routable address, publishing
it through a tunnel, or putting it behind a reverse proxy without
authentication gives everything above to anyone who can reach it.

It is not hardened for multi-user or internet-facing use, and no one should
rely on it to keep documents from people who can reach the service.

## What is in place

- **Loopback by default**, and an interlock: with `AUTH_ENABLED` off the app
  refuses to start unless `RAGLINE_ALLOW_INSECURE_DEV=1` is also set, so an
  instance intended to require sign-in cannot come up open because of a
  mistyped value. With auth on, it refuses to start if the identity-provider
  settings are missing.
- **Uploads**: ZIP entries are sanitised against path traversal. Server-side
  folder ingest is disabled unless `INGEST_ROOTS` allowlists directories, and
  requested paths are resolved and checked against that list.
- **Citations are constructed, not generated.** Source identity comes from
  retrieved chunks; a model cannot cite a document it was not given.
- **The pod env hook** (`scripts/apply_pod_env.py`) only accepts an allowlist
  of model-endpoint keys, so a handed-over block cannot change auth or storage
  settings, and it never prints values.
- **Secrets** live in `.env`, which is gitignored. Evaluation results record
  endpoint hosts with pod ids masked, and never keys.
- **`scripts/fetch_corpus.py`** refuses manifest paths that would write
  outside its destination directory.

## Known gaps

These are understood and not yet addressed. They are acceptable for a local
single-user tool and are the reasons it must not be exposed.

- **No authentication in the tested configuration.**
- **No upload limits.** There is no cap on file size or on the expanded size
  of a ZIP; a large or hostile upload can exhaust memory or disk.
- **No rate limiting**, and no CORS policy (the UI is served from the same
  origin).
- **Document content is trusted.** Text from ingested documents is placed in
  LLM prompts. A document can contain instructions aimed at the model (prompt
  injection); answers are constrained to cite retrieved sources, but nothing
  filters what those sources say.
- **Configured endpoints are trusted.** ragline sends document text, questions
  and conversation history to whatever `LLM_BASE_URL`, `EMBEDDING_BASE_URL`
  and `RERANKER_BASE_URL` point at, and does not restrict where those may
  point. Only ingest documents you are content to send to those services.
- **Stored data is not encrypted.** Uploaded files, the SQLite database and
  chat sessions sit in `./data/` as ordinary files.
- **Dependencies** are declared with lower bounds; `uv.lock` records the
  tested versions. There is no automated vulnerability scanning yet.

## The experimental multi-user mode

The repository contains an implementation of Entra ID sign-in, per-user
sessions and per-user gating of citation links by NTFS ACL (`src/ragline/auth`,
`src/ragline/acl`, [deploy/intranet/](deploy/intranet/RUNBOOK.md)). It is
unit-tested and has **not been validated against a real tenant, file server
or adversary**. It also has a documented design limit: retrieval is global, so
quoted snippets from any ingested document are visible to every signed-in
user — only the links and downloads are gated.

Reports about that code are welcome and in scope, but treat it as a design in
progress rather than a security boundary.

## Scope

In scope: the ragline application (`src/`, `frontend/`, `scripts/`,
`restart.sh`, `deploy/`). Out of scope: the model servers and GPU providers
you connect it to, the documents you ingest, and issues that require an
already-compromised local user account.
