# OpenRAG scripts

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
