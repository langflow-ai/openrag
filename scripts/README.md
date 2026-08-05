# OpenRAG scripts

## Bulk ingest (`openrag_bulk.py`)

`openrag_bulk.py` is a standalone client for loading a directory or a set of
files through OpenRAG's public ingestion API. It groups files into server tasks,
keeps a bounded number of tasks in flight, polls them to completion, and writes
an atomic `summary.json` record as the run progresses.

The command families are deliberately separate:

- `bulk upload` loads user-supplied files or directories.
- `bench arxiv` acquires a repeatable arXiv dataset, then delegates its upload
  phase to the same bulk loader.

The script has inline `uv` dependency metadata and does not import the OpenRAG
application or SDK, so it can also be copied and run outside this repository.

Set the URL of the OpenRAG frontend and an API key with `knowledge:upload` and
`knowledge:read:own` permissions:

```bash
export OPENRAG_URL=http://localhost:3000
export OPENRAG_API_KEY=orag_your_api_key

uv run scripts/openrag_bulk.py bulk upload ./documents \
  --include '*.pdf' \
  --exclude 'archive/*' \
  --batch-size 10 \
  --max-inflight 4 \
  --max-submit 2
```

`--batch-size` controls how many files are sent in each multipart request.
`--max-inflight` bounds the number of submitted OpenRAG tasks, including tasks
being uploaded or polled. `--max-submit` can impose a lower limit on concurrent
multipart requests, which is useful when files are large.

Useful upload options include:

| Option | Purpose |
| --- | --- |
| `--sort path\|size-asc\|size-desc` | Choose the order in which files are batched. |
| `--include GLOB`, `--exclude GLOB` | Filter relative paths or filenames; repeat either option. |
| `--no-recursive` | Only read files directly inside supplied directories. |
| `--settings-json JSON_OR_@FILE` | Forward per-run knowledge ingest settings. |
| `--tweaks-json JSON_OR_@FILE` | Forward Langflow ingest tweaks. |
| `--no-replace-duplicates` | Preserve existing documents with duplicate filenames. |
| `--task-timeout SECONDS` | Bound the wait for each submitted server task. |
| `--runs-dir DIR`, `--output-dir DIR`, `--run-id ID` | Control local run records. |

When connecting directly to the backend rather than through the frontend proxy,
select its route prefix explicitly:

```bash
uv run scripts/openrag_bulk.py bulk upload ./documents \
  --base-url http://localhost:8000 \
  --api-prefix /v1
```

Runs are stored under `~/.openrag/bulk/runs` by default. They can be inspected
without a running server or an API key:

```bash
uv run scripts/openrag_bulk.py bulk list
uv run scripts/openrag_bulk.py bulk summary
uv run scripts/openrag_bulk.py bulk summary --detail latest
```

The upload command exits with status `0` when every batch completes, `1` when
one or more batches/files fail, and `2` for invalid input or configuration.

### arXiv benchmark and PDF downloader

The same standalone client includes the arXiv benchmark from `openrag-lite`.
It can stage PDFs without a server, or feed the staged PDFs directly into the
bulk uploader above.

By default, the benchmark copies a requester-pays arXiv PDF tarball from S3,
caches the tarball, extracts the selected PDFs, and uploads them to OpenRAG:

```bash
export OPENRAG_URL=http://localhost:3000
export OPENRAG_API_KEY=orag_your_api_key

uv run scripts/openrag_bulk.py bench arxiv \
  --max-results 100 \
  --batch-size 10 \
  --max-inflight 4
```

The S3 path requires the AWS CLI and credentials that can read the
requester-pays `s3://arxiv` bucket. Override `--s3-uri` to use another tarball;
plain local paths and `file://` URLs are also supported.

To query arXiv's Atom API and download PDFs individually instead, select the
Atom source. The client applies a three-second courtesy delay between arXiv
requests by default:

```bash
uv run scripts/openrag_bulk.py bench arxiv \
  --source atom \
  --category cs.AI \
  --date-from 2025-01-01 \
  --date-to 2025-01-31 \
  --max-results 25
```

`--query` accepts a raw arXiv search query and overrides the category/date
query. `--start`, `--sort-by`, and `--sort-order` control source selection.

Download and cache PDFs without connecting to OpenRAG by passing
`--download-only`; no API key is required:

```bash
uv run scripts/openrag_bulk.py bench arxiv \
  --source atom \
  --query 'cat:cs.CL' \
  --max-results 10 \
  --download-only
```

The PDF cache defaults to `~/.openrag/benchmarks/arxiv/pdfs`. Existing PDFs and
S3 tarballs are reused by default. Atom download failures are remembered in
`_failed_downloads.json`; pass `--retry-failed-downloads` to try them again, or
`--no-skip-existing` to create fresh PDF files.

Benchmark run records default to `~/.openrag/benchmarks/arxiv/runs`:

```bash
uv run scripts/openrag_bulk.py bench arxiv list
uv run scripts/openrag_bulk.py bench arxiv summary
uv run scripts/openrag_bulk.py bench arxiv summary --detail latest
```

## Sync default user roles (`sync_default_user_roles.py`)

Dev-only helper for RBAC in **OSS run mode** (`OPENRAG_RUN_MODE=oss`): updates
existing users in the SQL DB when `OPENRAG_DEFAULT_ROLE` changes. Requires:

```env
OPENRAG_RUN_MODE=oss
OPENRAG_SYNC_DEFAULT_ROLE=true
OPENRAG_DEFAULT_ROLE=admin   # target role: admin | developer | user | viewer
```

Ignored in `saas` and `on_prem` — those modes assign roles from JWT claims.

Uses the default SQLite DB at `data/openrag.db` unless `DATABASE_URL` is set.

### Promote all `user` roles to `OPENRAG_DEFAULT_ROLE`

Use this when users still have the `user` role but you want them on whatever
role is set in `OPENRAG_DEFAULT_ROLE` (for example `admin`):

```bash
OPENRAG_SYNC_DEFAULT_ROLE=true \
OPENRAG_DEFAULT_ROLE=admin \
uv run python scripts/sync_default_user_roles.py --from-role user
```

### Explicit from → to (ignores env target)

When both roles are on the CLI, the target comes from `--to-role`, not
`OPENRAG_DEFAULT_ROLE`:

```bash
OPENRAG_SYNC_DEFAULT_ROLE=true \
uv run python scripts/sync_default_user_roles.py --from-role admin --to-role user
```

Migrates every user whose **only** role is `admin` to `user`, regardless of
what `OPENRAG_DEFAULT_ROLE` is set to.

What it does:

- Finds every user whose **only** role is `user`
- Assigns them the role from `OPENRAG_DEFAULT_ROLE` (here: `admin`)
- Skips users with multiple roles or a different single role
- Updates the stored baseline in `workspace_config.meta`

Preview without writing:

```bash
OPENRAG_SYNC_DEFAULT_ROLE=true \
OPENRAG_DEFAULT_ROLE=admin \
uv run python scripts/sync_default_user_roles.py --from-role user --dry-run
```

Replace `user` with any source role, and set `OPENRAG_DEFAULT_ROLE` to the
target role you want.

### Other commands

| Command | Purpose |
| --- | --- |
| `uv run python scripts/sync_default_user_roles.py` | Sync when env default changed since last recorded baseline |
| `--dry-run` | Show changes without writing to the DB |
| `--from-role ROLE` | Source role for this run (overrides stored baseline) |
| `--to-role ROLE` | Target role (overrides `OPENRAG_DEFAULT_ROLE`; requires `--from-role`) |
| `--from-noauth-role ROLE` | Source role for the anonymous user |
| `--to-noauth-role ROLE` | Target role for anonymous user (overrides `OPENRAG_NOAUTH_ROLE`) |
| `--record-baseline` | Save current env defaults; do not change any user |

### After running

Restart the backend (or wait for `OPENRAG_PERM_CACHE_TTL`, default 60s) so
permission checks pick up the new roles. Verify with:

```bash
curl -b "auth_token=..." http://localhost:8000/users/me
```

### Notes

- Intended for local OSS dev workflows, not production role management.
- If the script reports stale users but updates none, use `--from-role` with
  the role those users currently have.

## Reset onboarding (`reset_onboarding.py`)

Re-triggers the onboarding wizard by resetting workspace config in the DB
(`OPENRAG_STORAGE_MODE=db` by default):

```bash
uv run python scripts/reset_onboarding.py
```

What it does:

- Sets `workspace_config.meta.edited` to `false` (`GET /api/onboarding-status` → `onboarded: false`)
- Clears `workspace_config.onboarding` (including `current_step` → `0`)
- In `hybrid` / `files` mode, also updates `config.yaml`

Optional flags:

| Flag | Purpose |
| --- | --- |
| `--dry-run` | Preview without writing |
| `--reset-models` | Also clear selected LLM and embedding models |

Example — full wizard reset including model picks:

```bash
uv run python scripts/reset_onboarding.py --reset-models
```

After running, **restart the backend** and reload the app.

This script does **not** delete ingested documents, knowledge filters, Langflow
flows, or conversations. For a full teardown, use the authenticated API endpoint
`POST /settings/rollback-onboarding` instead.
