# Offline OpenRAG key rotation (SQLite)

Run from the checkout containing this script. This wrapper assumes the SQLite database is `openrag.db` inside the existing data directory. For PostgreSQL, non-default database paths, or OAuth caches outside the normal data tree, follow the [full runbook](../../docs/docs/reference/rotate-encryption-key.mdx).

Install backend dependencies with `uv sync --locked`. Stop OpenRAG and all writers for a consistent final backup. Set the paths in the same Bash session:

```bash
export OLD_DATA_DIR=/absolute/path/to/existing/data
export OLD_CONFIG_DIR=/absolute/path/to/existing/config
export OLD_DATA_PATH_AS_STORED=data  # original prefix in connector references
export OPENRAG_TENANT_ID=openrag      # use the existing deployment's tenant
export MIGRATION_DIR=/private/existing/parent/openrag-key-rotation
```

`MIGRATION_DIR` must not exist yet. Use a private parent outside both source directories. `OLD_DATA_PATH_AS_STORED` is how the app saw the data directory (such as `data` or an absolute container path), not necessarily the host's `OLD_DATA_DIR`.

```bash
# 1. Create the untouched backup and separate working restore.
bash scripts/migration/rotate-key.sh backup

# 2. Paste the existing key at the hidden prompt. This also generates a new key.
bash scripts/migration/rotate-key.sh keys

# 3. Read-only preflight against the working restore.
bash scripts/migration/rotate-key.sh dry-run
```

Review the preflight counts against your backup inventory. Stop on any error or unexpected count. Once satisfied:

```bash
# 4. Rotate the working restore, then verify using only the new key.
bash scripts/migration/rotate-key.sh apply
```

`$MIGRATION_DIR/backup` stays untouched during rotation. `$MIGRATION_DIR/restore` is the copy that gets rotated. `$MIGRATION_DIR/keys/old` and `keys/new` contain the key values; protect them and save both in your secret manager before cutover. The script does not start services or switch deployment data or keys. If apply or verification fails, don't promote that copy; start with a fresh restore. Follow the runbook for cutover and rollback. The Kubernetes Operator does not support an in-place key change.
