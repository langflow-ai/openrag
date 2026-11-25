# Offline OpenRAG key rotation (SQLite)

Copy this entire folder to the migration host. No OpenRAG checkout is needed. This wrapper assumes the SQLite database is `openrag.db` inside the existing data directory. For PostgreSQL, non-default database paths, or OAuth caches outside the normal data tree, follow the [full runbook](https://github.com/langflow-ai/openrag/blob/main/docs/docs/reference/rotate-encryption-key.mdx).

Use Python 3.13 (the OpenRAG-supported version). From the copied folder, create an isolated environment before stopping writers:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export MIGRATION_PYTHON="$PWD/.venv/bin/python"
```

Stop OpenRAG and all writers for a consistent final backup. Set these paths in the same Bash session:

```bash
export OLD_DATA_DIR=/absolute/path/to/existing/data
export OLD_CONFIG_DIR=/absolute/path/to/existing/config
export OLD_DATA_PATH_AS_STORED=data  # original prefix in connector references
export OPENRAG_TENANT_ID=openrag      # use the existing deployment's tenant
# New workspace for backup/, restore/, and keys/. Its private parent must already exist.
export MIGRATION_DIR=/private/existing/parent/openrag-key-rotation
```

## What each command does

| Command | What it changes |
| --- | --- |
| `backup` | Copies the source into `backup/` and creates a separate working copy in `restore/`. Both still use the old key. |
| `keys` | Prompts for both keys without echoing them and saves them in protected files under `keys/`. Does not generate or install a key. |
| `dry-run` | Checks that the old key decrypts the working copy and reports ciphertext counts. Changes nothing. |
| `check` | Authenticates ciphertext in the selected SQLite data and config directories with a supplied key. Reports counts without changing anything. Unlike `dry-run`, it is not tied to `restore/` or the old key. |
| `apply` | Rotates and verifies `restore/` using the replacement key. Leaves the original and `backup/` untouched. |
| `cutover-data` | Re-verifies the rotated copy, checks the destinations against `backup/`, then moves the restore into place after confirmation. Keeps the replaced directories for rollback. Does not change keys or start OpenRAG. |
| `cleanup keys`, `cleanup restore`, `cleanup backup` | Removes only the named workspace directory after confirmation. Does not remove the saved original runtime directories. |

`MIGRATION_DIR` must not exist yet. Use a private parent outside both source directories. `OLD_DATA_PATH_AS_STORED` is how the app saw the data directory (such as `data` or an absolute container path), not necessarily the host's `OLD_DATA_DIR`.

```bash
# 1. Create the untouched backup and separate working restore.
bash rotate-key.sh backup

# 2. Paste the existing key and then your replacement key at the hidden prompts.
bash rotate-key.sh keys

# 3. Read-only preflight against the working restore.
bash rotate-key.sh dry-run
```

The script does not generate a key. Supply a replacement key that is Base64 for exactly 32 bytes; the dry run validates its format.

Review the preflight counts against your backup inventory. Stop on any error or unexpected count. Once satisfied:

```bash
# 4. Rotate the working restore, then verify using only the new key.
bash rotate-key.sh apply
```

`apply` leaves the original and `$MIGRATION_DIR/backup` untouched. If it fails, start with a fresh restore. Save both keys in your secret manager before cutover.

For **self-managed SQLite only**, with OpenRAG and all writers stopped, promote the verified restore into the existing runtime paths:

```bash
bash rotate-key.sh cutover-data \
  --original-data-dir /absolute/runtime/data \
  --original-config-dir /absolute/runtime/config
```

With no arguments, `cutover-data` uses `OLD_DATA_DIR` and `OLD_CONFIG_DIR`. Use that shorthand only if both exports are the real runtime directories. If they point to a staged restore, pass both runtime paths explicitly. Always check the destinations shown before confirming.

Use separate, non-mounted directories on the same filesystem as the restore. The command checks that the destinations still match the backup, asks for confirmation, and prints where it saved the old directories. It consumes `restore/data` and `restore/config` and leaves `backup/` untouched. It does not update secrets or start the app. Set the replacement key before starting the backend. Use the runbook for Operator-managed deployments and rollback.

Cutover checks the restore against the file hashes recorded by `apply`. It refuses modified restores or runtime directories with ACLs; use manual cutover for ACL-dependent deployments.

Progress messages go to stderr; rotation counts go to stdout. Terminal labels are colored unless `NO_COLOR=1` is set. When looping over deployments, use a distinct `MIGRATION_DIR` for each and stop on any nonzero exit. Review each dry run before applying; do not put dry run and apply in the same unattended loop.

## Check runtime data before restarting

Keep OpenRAG writers stopped. After cutover, check the actual runtime directories with the replacement key before restarting:

```bash
# Use OLD_DATA_DIR, OLD_CONFIG_DIR, and $MIGRATION_DIR/keys/new if available.
bash rotate-key.sh check

# Override the directories and use a protected one-line key file.
bash rotate-key.sh check \
  --data-dir /absolute/runtime/data --config-dir /absolute/runtime/config \
  --key-file /secure/keys/replacement

# Ignore the saved replacement key and paste a key at a hidden prompt.
bash rotate-key.sh check --prompt-key
```

If the exports point at staging, pass the real runtime paths explicitly. If no key file is specified or saved, `check` prompts automatically; `MIGRATION_DIR` is not needed when using an explicit key file or the prompt. The check fails if decryption fails or there is no ciphertext to authenticate. It does not check which key OpenRAG will load; configure the matching key separately.

## Clean up one directory at a time

```bash
bash rotate-key.sh cleanup keys     # After saving both keys securely
bash rotate-key.sh cleanup restore  # Only when no deployment uses it
bash rotate-key.sh cleanup backup   # Only after the rollback window closes
```

Each command shows the exact directory and asks you to type its name. Cleanup is never automatic.
