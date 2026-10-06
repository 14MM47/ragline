#!/usr/bin/env bash
# restart.sh — dev convenience: ensure Qdrant is up, then (re)start the API.
# Ported from raggles' restart.sh, simplified.

set -euo pipefail

# Repo root = directory containing this script; run everything from there.
cd "$(dirname "$0")"

# --- 1. Ensure Qdrant is running (via docker compose) -----------------------
# `up -d` is idempotent: starts the service if stopped, no-op if running.
docker compose up -d qdrant

# --- 2. Kill any stale API process holding port 8000 ------------------------
# fuser exits non-zero when nothing holds the port; that's fine (|| true).
fuser -k 8000/tcp 2>/dev/null || true

# --- 3. Start uvicorn -------------------------------------------------------
# Prefer the project venv if present; otherwise rely on PATH.
if [ -x ".venv/bin/uvicorn" ]; then
    UVICORN=".venv/bin/uvicorn"
else
    UVICORN="uvicorn"
fi

# Bind loopback unless told otherwise: with AUTH_ENABLED=false every request
# runs as one admin-capable dev user, so a routable address would hand the
# corpus (and the delete buttons) to the whole network. Override deliberately:
#   HOST=0.0.0.0 ./restart.sh
HOST="${HOST:-127.0.0.1}"

# exec replaces this shell with uvicorn so signals (Ctrl-C) reach it directly.
# --app-dir src lets uvicorn import the package from the src/ layout.
exec "$UVICORN" ragline.main:app --host "$HOST" --port 8000 --app-dir src
