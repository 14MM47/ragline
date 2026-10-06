# Publishing the first public repository

The first public repository starts with one root commit of the reviewed
release tree. The existing private repository and its history stay private.
Run these commands in Bash/WSL. They are maintainer instructions, not part of
the application startup.

## Finalize the release tree

Review and commit all intended changes in the private repository first.
Inspect staged files before committing. Work from the finalized release
branch and require a clean working tree so the export cannot silently omit
uncommitted fixes:

```bash
set -euo pipefail
test -z "$(git status --porcelain)"
release_revision=$(git rev-parse HEAD)
```

Run the release checks:

```bash
uv sync --locked --extra dev --extra ocr
uv run ruff check .
uv run pytest tests/unit -q
(cd frontend && npm ci && npx tsc --noEmit && npm test && npm run build)
```

With the original PDFs available, regenerate the corpus index and review any
digest changes. Commit any resulting corrections, repeat affected checks, and
capture the finalized revision again. Confirm the relative documentation
links resolve and the licence notices match the locked dependencies.

## Export files into independent history

Archive that exact commit into a new empty directory. Git archive includes
only committed files and does not copy the private repository's Git metadata:

```bash
release_dir=$(mktemp -d "${TMPDIR:-/tmp}/ragline-public.XXXXXX")
git archive "$release_revision" | tar -x -C "$release_dir"
cd "$release_dir"
git init -b main
git config user.name 14MM47
git config user.email YOUR_GITHUB_NOREPLY_EMAIL
git add --all
git diff --cached --stat
```

Replace the email placeholder with your actual GitHub noreply email before
committing. Check the staged tree for environment files, runtime state,
PDFs, local assistant files, credentials and private identifiers.
The ignore file is not a substitute for inspecting what is staged.

Run [Gitleaks](https://github.com/gitleaks/gitleaks) on this exported tree
with findings redacted:

```bash
gitleaks dir . --redact
```

Also compare the original environment-file secret values against the exported
files without printing those values. Pattern scanners cannot recognize every
custom bearer. Review evaluation answers, errors and logs, corpus source URLs,
and deployment examples for private information.

After these checks pass:

```bash
git commit -m "Initial public release"
test "$(git rev-list --count --all)" -eq 1
test "$(git rev-list --max-parents=0 --count --all)" -eq 1
test "$(git for-each-ref --format='%(refname)' | wc -l)" -eq 1
test -z "$(git remote)"
gitleaks git . --redact
```

Do not copy the private `.git` directory, clone the private repository for
this export, or push its branches and tags to the new repository.

## Stage on GitHub privately

The documentation assumes `14MM47/ragline`. If the private repository
already owns that name, rename it to `ragline-private` through GitHub and
update the origin URL in the **original private checkout**. Verify it remains
private. Complete that step before creating the new repository.

From the independent export directory:

```bash
gh repo create 14MM47/ragline --private --source=. --remote=origin --push
gh repo view 14MM47/ragline --json nameWithOwner,isPrivate,defaultBranchRef
gh run list --repo 14MM47/ragline --workflow ci.yml
```

Wait for the CI run on the exact commit you pushed and check every matrix
job; `gh run watch RUN_ID --repo 14MM47/ragline --exit-status` waits for that
run. If fixes are needed, incorporate them into the finalized private source
tree and prepare a new one-commit export. Keep the staging repository private
until its final commit and contents have been reviewed.

Clone the staging repository into a separate empty directory, verify there is
exactly one commit, and repeat the quickstart with `env.template`. Confirm
loopback binding, the UI and `/api/health`; model health requires configured
endpoints. Do not copy local data or secrets into the staged repository.

## Publish and enable vulnerability reports

Making the staging repository public is the final publication action:

```bash
gh repo edit 14MM47/ragline --visibility public --accept-visibility-change-consequences
gh api --method PUT repos/14MM47/ragline/private-vulnerability-reporting
gh api repos/14MM47/ragline/private-vulnerability-reporting    # expect {"enabled":true}
gh repo view 14MM47/ragline --json nameWithOwner,isPrivate,defaultBranchRef
```

`gh repo edit` has no flag for private vulnerability reporting, so that
setting goes through the REST API.

GitHub's private vulnerability reporting setting is required for the reporting
channel linked by [SECURITY.md](../SECURITY.md) and the issue template.
Check the repository's Security tab, the reporting link and the latest CI
run after publication. Verify the original repository is still private and its
checkout still points at `ragline-private`.

Command references:
[repository creation](https://cli.github.com/manual/gh_repo_create),
[repository settings](https://cli.github.com/manual/gh_repo_edit),
[private vulnerability reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).
