#!/usr/bin/env bash
# ragline-backup.sh — nightly backup of everything stateful.
#
# Covers: SQLite metadata DB (.backup is WAL-safe and non-blocking), the
# uploaded-file store, chat memory, and a Qdrant snapshot. The hypervisor's
# VM snapshot is NOT a substitute: SQLite + Qdrant need their own consistent
# capture, and an off-VM copy survives the VM itself.
#
# Install: deploy/intranet/systemd/ragline-backup.{service,timer}. Configure the
# destination below or via RAGLINE_BACKUP_DIR. Run a RESTORE DRILL once —
# an untested backup is a hope, not a backup (see deploy/intranet/RUNBOOK.md).

set -euo pipefail

RAGLINE_HOME="${RAGLINE_HOME:-/opt/ragline}"
BACKUP_DIR="${RAGLINE_BACKUP_DIR:-/var/backups/ragline}"
KEEP_DAYS="${RAGLINE_BACKUP_KEEP_DAYS:-14}"
QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
# Must match QDRANT_COLLECTION in .env (the snapshot API is per collection).
COLLECTION="${QDRANT_COLLECTION:-ragline}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${BACKUP_DIR}/${STAMP}"

mkdir -p "${DEST}"

# 1. SQLite — .backup takes a consistent copy while the app keeps writing.
sqlite3 "${RAGLINE_HOME}/data/ragline.db" ".backup '${DEST}/ragline.db'"

# 2. Uploaded files + chat memory (managed copies + per-user sessions).
tar -czf "${DEST}/uploads.tar.gz" -C "${RAGLINE_HOME}/data" uploads
tar -czf "${DEST}/memory.tar.gz" -C "${RAGLINE_HOME}/data" memory

# 3. Qdrant snapshot via its API (loopback only). The container's snapshots
#    dir is bind-mounted from the host (docker-compose.yml), so the file is
#    copied straight off the filesystem — this script needs no docker access
#    and runs unprivileged. Cleanup goes back through the API so Qdrant (which
#    owns the files) does the deleting.
SNAPSHOT_NAME="$(curl -sf -X POST "${QDRANT_URL}/collections/${COLLECTION}/snapshots" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["name"])')"
cp "${RAGLINE_HOME}/data/qdrant-snapshots/${COLLECTION}/${SNAPSHOT_NAME}" "${DEST}/qdrant-${SNAPSHOT_NAME}"
curl -sf -X DELETE "${QDRANT_URL}/collections/${COLLECTION}/snapshots/${SNAPSHOT_NAME}" > /dev/null

# 4. Rotate.
find "${BACKUP_DIR}" -mindepth 1 -maxdepth 1 -type d -mtime "+${KEEP_DAYS}" -exec rm -rf {} +

echo "backup complete: ${DEST}"
# 5. Off-VM copy: rsync ${DEST} to your backup target here (site-specific).
