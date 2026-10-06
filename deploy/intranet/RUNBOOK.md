# ragline intranet deployment runbook (experimental)

> **Status: experimental, not production-validated.** ragline is a
> proof-of-concept that is developed and tested as a single-user tool on a
> local machine (see the top-level [README](../../README.md)). The multi-user
> surface described here — Entra SSO, per-user sessions, NTFS ACL gating, the
> systemd/nginx/backup units — is implemented and unit-tested, but it has
> **not been run against a real tenant or file server**. Treat this document
> as a design record and a starting point, not a hardened deployment guide,
> and read [SECURITY.md](../../SECURITY.md) first.

How the build is meant to go onto an intranet VM, from bare VM to per-user
ACL-gated citations. Nothing in this repo touches a server by itself — every
step here is an explicit operator action.

Companion artifacts (all in-repo):

| Artifact | Purpose |
|---|---|
| `deploy/intranet/systemd/ragline.service` | the app under systemd (single worker — hard constraint) |
| `deploy/intranet/systemd/ragline-qdrant.service` | Qdrant via docker compose |
| `deploy/intranet/systemd/ragline-acl.{service,timer}` | nightly NTFS ACL crawl |
| `deploy/intranet/systemd/ragline-backup.{service,timer}` + `deploy/intranet/backup/ragline-backup.sh` | nightly backups |
| `deploy/intranet/nginx/ragline.conf` | TLS termination + SSE-safe reverse proxy |
| `scripts/acl_spike.py` | day-1 validation of the whole ACL design |
| `scripts/acl_crawl.py` | the crawler the timer runs |

## 0. Prerequisites (people/other-team actions)

- **VM**: Ubuntu 24.04, 8 vCPU / 16 GB RAM / 150 GB disk, static IP, internal
  DNS record (e.g. `ragline.<corp>`).
- **TLS certificate** for that name from the internal CA (the CA root must be
  trusted on user devices). HTTPS is load-bearing: the Entra redirect URI,
  the Secure session cookie, and the copy-network-path button all require it.
- **Entra app registration** (tenant admin) — record tenant/client id + secret:
  - Single tenant, platform **Web**, redirect URI `https://ragline.<corp>/api/auth/callback`.
  - Token configuration → groups claim: **Security groups** as **Group IDs**
    in the **ID token**.
  - Delegated permissions: `openid`, `profile`, `email`, `offline_access`,
    `User.Read`. **`offline_access` is required** — it yields the refresh
    token that powers silent session re-validation; without it every user is
    forced to re-login each `SESSION_REVALIDATE_MINUTES`.
  - Application permission `GroupMember.Read.All` + admin consent — **only if
    any user is in >200 security groups** (the token overage fallback).
    Otherwise DO NOT grant it: it is the sole standing tenant-wide
    permission, and app-only tokens bypass Conditional Access, so a stolen
    client secret + this permission = tenant-wide group enumeration from
    anywhere. Without it the secret is only usable against this app's own
    redirect URI.
  - Client secret: note the expiry date in the rotation calendar (§6).
    Prefer delivering it via systemd `LoadCredential=` + the
    `ENTRA_CLIENT_SECRET_FILE` setting (template in `ragline.service`) so it
    never sits in `.env`.
- **SMB service account**: non-interactive; NTFS **Read** role (includes Read
  Permissions/READ_CONTROL) + share-level Read on every share that appears in
  `original_path`. No write access anywhere.
- An **admin security group** for ragline admins; its object id becomes
  `ENTRA_ADMIN_GROUP_ID`.

## 1. Install the app

```bash
sudo useradd --system --home /opt/ragline ragline
sudo git clone <repo> /opt/ragline && cd /opt/ragline
sudo -u ragline uv sync --extra ocr
cd frontend && npm ci && npm run build   # or build on a dev box and rsync frontend/dist
sudo chown -R ragline:ragline /opt/ragline
```

`.env` (copy `env.template`, `chmod 600`, owner `ragline`): carry over the
LLM/embedding/reranker endpoint values, then set **absolute paths** and auth
(the template ships with auth OFF for local use — both lines marked `!` must
change):

```
DATABASE_URL=sqlite+aiosqlite:////opt/ragline/data/ragline.db
UPLOAD_DIR=/opt/ragline/data/uploads
MEMORY_DIR=/opt/ragline/data/memory
FRONTEND_DIST=/opt/ragline/frontend/dist
AUTH_ENABLED=true                 # ! template ships false
RAGLINE_ALLOW_INSECURE_DEV=       # ! template ships 1 — must be blank here
ENTRA_TENANT_ID=... ENTRA_CLIENT_ID=... ENTRA_CLIENT_SECRET=...
ENTRA_ADMIN_GROUP_ID=...
SESSION_SECRET=$(openssl rand -hex 32)
APP_BASE_URL=https://ragline.<corp>
SMB_USERNAME=... SMB_PASSWORD=...
```

Migrate data from a local instance: rsync `data/` (db + uploads + memory) and move
the Qdrant volume (snapshot API, or tar the docker volume with both sides
stopped).

## 2. Services

```bash
sudo cp deploy/intranet/systemd/*.service deploy/intranet/systemd/*.timer /etc/systemd/system/
sudo cp deploy/intranet/nginx/ragline.conf /etc/nginx/sites-available/ragline   # edit server_name + cert paths
sudo ln -s ../sites-available/ragline /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl daemon-reload
sudo systemctl enable --now ragline-qdrant ragline
# Backup destination for the (unprivileged) backup unit — one-time setup.
sudo install -d -o ragline -g ragline -m 750 /var/backups/ragline
sudo systemctl enable --now ragline-backup.timer
# ragline-acl.timer comes in §4, AFTER the spike validates the design.
sudo ufw allow 443/tcp && sudo ufw allow from <mgmt-subnet> to any port 22 && sudo ufw default deny incoming && sudo ufw enable
```

Verification pass:
- `curl -k https://ragline.<corp>/api/health` is green.
- Browser: hitting the bare URL redirects to Microsoft sign-in (MFA applies),
  lands back signed in; the header shows your name.
- Chat: the answer **streams incrementally** — if it arrives in one lump,
  nginx buffering is misconfigured (`proxy_buffering off` on the site).
- Citation sidebar: "Open copy" works; copy-network-path works (HTTPS!).
- Two different users see disjoint chat-session lists.
- `ss -tlnp`: externally only 443 (+22 from mgmt); 8000/6333/6334 loopback.
- Reboot the VM; everything comes back by itself.

## 3. What auth changes for existing users

- Chat sessions are now **per user** (`data/memory/<oid>/`). Pre-auth loose
  sessions were parked in `data/memory/_legacy/` at first startup — recover a
  specific file by copying it into a user's folder, or delete `_legacy` once
  nobody misses anything.
- Uploads record the uploader's UPN in `Document.uploaded_by`.
- **Auth cannot be disabled on the VM by accident.** The app refuses to
  start whenever auth is off (any falsey `AUTH_ENABLED` — `false`/`0`/`no`/
  `off`) unless `RAGLINE_ALLOW_INSECURE_DEV=1` is explicitly set in the
  environment; that check keys off the parsed value, so no spelling or
  systemd `Environment=` override slips past. `ragline.service` also fails at
  `ExecStartPre` on a disabled `.env` as defense-in-depth. Local single-user
  machines set `RAGLINE_ALLOW_INSECURE_DEV=1` (the shipped `env.template`
  does); a shared VM never does — blank it when copying the template.
- **Revocation**: sessions silently re-validate against Entra every
  `SESSION_REVALIDATE_MINUTES` (default 60) via the stored refresh token —
  disabling an account, "Revoke sign-in sessions" in the portal, or a
  Conditional Access change kills ragline sessions within one interval, and
  group changes propagate on the same cadence. During an Entra outage
  existing sessions stay alive (accepted trade-off); new logins fail.
  **Immediate revocation** (incident/offboarding): an admin calls
  `POST /api/admin/users/{oid}/revoke-sessions` — takes effect on the
  target's next request.
- **Cross-site defence**: state-changing requests must carry an `Origin`
  matching `APP_BASE_URL` (sibling `*.corp` hosts are "same-site" to
  cookies, so SameSite alone is not enough on an intranet). Non-browser
  clients (curl, scripts) are unaffected — they send no Origin.
- Logout is a POST; set `LOGOUT_FROM_ENTRA=true` on shared/kiosk deployments
  so signing out also ends the Entra browser session (otherwise the next
  user's login silently resumes the previous account).

## 4. The ACL layer — spike FIRST, then enable

The design assumes cloud-only Entra: DACLs on the shares carry `S-1-12-1-*`
SIDs (derived from Entra object GUIDs) and well-known SIDs. **Validate that
before trusting anything**:

```bash
sudo -u ragline uv run python scripts/acl_spike.py '\\fs1\share\known-file.pdf' ... # ~20 mixed files
```

Read the output: does READ_CONTROL work? Are the SIDs the expected cloud +
well-known population, or is something else (legacy domain SIDs?) granting
read? Anything the resolver marks IGNORED can only deny, never allow — a
corpus full of ignored allow-ACEs means the assumption is wrong; stop and
reassess before enabling the timer.

Then: `sudo systemctl enable --now ragline-acl.timer` (nightly 02:30 + 15 min
after boot), and run one crawl by hand to seed:
`sudo systemctl start ragline-acl.service`.

Semantics (all fail closed):
- Blank/non-UNC `original_path` → nobody can open that citation.
- Crawl failures keep the previous grants until `ACL_STALE_DAYS` (7) expires
  them; a dead crawler degrades to "citations lock", never to stale access.
- ACL changes on the file server take effect at the **next crawl**; group
  membership changes at next login (or the 24 h Graph TTL refresh).
- `GET /api/admin/acl-status` (admin group only) shows counts per status and
  exactly which documents are failing and why. Fix wrong `original_path`
  values directly in SQLite (`UPDATE document SET original_path=... WHERE
  id=...`) — the field is deliberately not in Qdrant, so **no re-ingest is
  needed**; the next crawl picks corrections up.

End-to-end acceptance (two test users, one test share):
one Everyone-readable file, one group-restricted, one single-user, one
no-access. Verify link visibility differs per user AND that hand-crafting
`/api/documents/<id>/content` URLs returns 403 regardless of the UI.

## 5. Accepted risks — state these explicitly to whoever owns the data

1. **Search is global by design.** Retrieved snippets/quoted text from
   restricted documents are visible to every signed-in user; only the source
   links and downloads are gated. If a document is too sensitive for its
   snippets to be seen by every user, it must not be ingested.
2. `data/uploads` holds managed copies of every ingested file outside NTFS
   ACLs. VM compromise = corpus disclosure; that is what the VM hardening,
   loopback binds, and firewall are for (consider disk encryption too).
3. During an Entra outage no new sign-ins are possible (existing sessions
   keep working). A break-glass local account was considered and declined.

## 6. Rotation calendar & ops

| Secret | Where | Cadence |
|---|---|---|
| Entra client secret | Entra portal + `.env`/credential file | before its Entra expiry (set a reminder at creation) |
| TLS certificate | internal CA + nginx | per CA policy (typically yearly) |
| `SESSION_SECRET` | `.env`/credential file | on suspicion of compromise (signs every cookie AND encrypts stored refresh tokens — rotation logs everyone out) |
| SMB service-account password | AD/file server + `.env`/credential file | per org policy |

Secrets can live outside `.env` via the `*_FILE` settings + systemd
`LoadCredential=` (see `ragline.service`) — preferred for the Entra client
secret in particular.

After any `.env` change: `sudo systemctl restart ragline`.

- **Backups**: nightly timer (01:45) → `/var/backups/ragline/<stamp>/`;
  add the site-specific off-VM rsync in `ragline-backup.sh` step 5. **Run one
  restore drill**: restore into a scratch dir, point a spare `.env` at it,
  start uvicorn on a high port, ask a question, open a citation.
- **Monitoring**: external probe of `/api/health` (unauthenticated by
  design; anonymous callers get `{"status": ...}` only — per-service detail
  requires a session); alert on `ragline-acl.service` failure (uncomment `OnFailure=`
  once an alert unit exists); disk-space alert on `/opt/ragline` +
  `/var/backups`.
- **Logs**: journald (`journalctl -u ragline -u ragline-acl`); cap retention
  in `/etc/systemd/journald.conf` (`SystemMaxUse=2G`).

## 7. Deliberate deferrals

- **Alembic baseline**: the schema still moves; `create_all`
  remains the mechanism (as `metadata_db.py` documents). Add the baseline
  when the auth/ACL schema freezes — before the FIRST destructive migration,
  not after.
- **Postgres**: SQLite + WAL is fine at test-corpus size; Postgres is the
  scaling path.
- **Entra front-channel single-logout**: available behind
  `LOGOUT_FROM_ENTRA=true` for shared/kiosk deployments; the default stays
  local-only so "sign out of ragline" doesn't mean "sign out of M365".
