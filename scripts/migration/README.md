# Offline key rotation for OpenRAG SQLite files

Copy this folder to the migration host. No OpenRAG checkout is needed. This guide covers file migration for `openrag.db` and `connections.json` only. For other layouts, see the [production runbook](https://github.com/langflow-ai/openrag/blob/main/docs/docs/reference/rotate-encryption-key.mdx).

Use Python 3.13 (the OpenRAG-supported version). From the copied folder, create an isolated environment before stopping writers:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export MIGRATION_PYTHON="$PWD/.venv/bin/python"
```

## Pass two explicit files instead of directories

Use this mode only for a SQLite deployment where `openrag.db` and `connections.json` share a directory and are the only files that need rotation. It refuses `config.yaml`, discovered OAuth caches, and legacy state files; use the full restore workflow for those layouts. Keep writers stopped from backup through cutover, and checkpoint SQLite so no journal, WAL, or SHM files remain.

Create a private directory **outside the data directory** for the key files. `files keys` prompts for your current and replacement keys without echoing them. It saves them under `$MIGRATION_DIR/keys/` and does not generate a key. The replacement must be Base64 for exactly 32 bytes.

```bash
export MIGRATION_DIR="$(mktemp -d)"
bash rotate-key.sh files keys
```

```bash
DATA=/app/backend-data  # Use the actual parent of the two files.
files=(
  --sqlite "$DATA/openrag.db"
  --connections "$DATA/connections.json"
)

bash rotate-key.sh files backup "${files[@]}" &&
  bash rotate-key.sh files dry-run "${files[@]}"
```

| Command | What changes |
| --- | --- |
| `files keys` | Reads both keys from hidden prompts and saves protected `keys/old` and `keys/new` files. Does not modify the application or existing key files. |
| `files backup` | Creates `openrag.db.backup` and `connections.json.backup` beside the originals. Requires no keys and never overwrites a backup. |
| `files dry-run` | Checks the old key and reports ciphertext counts without writing files. |
| `files apply` | Uses the existing backups after checking they still match the originals. If neither backup exists, creates both. Writes and verifies the two `.migrated` files and their verification receipt; does not replace the originals. |
| `files check` | Decrypts and authenticates the specified files using the saved replacement key. Add `--migrated` to check their `.migrated` siblings instead, or `--key-file PATH` to use a different key. Does not modify either set. |
| `files cutover` | Re-verifies the migrated files, checks that the originals still match the backups, and asks you to confirm. Replaces only the two specified originals. Keeps both sets of sibling copies. |

Backups are **files**, not a backup directory: for example, `/app/backend-data/openrag.db.backup` and `/app/backend-data/connections.json.backup`. The wrapper prints progress and artifact paths to stderr and ciphertext counts to stdout. It never prints key values or decrypted data.

After reviewing the dry run and confirming the old key is recoverable:

```bash
bash rotate-key.sh files apply "${files[@]}" &&
  bash rotate-key.sh files check "${files[@]}" --migrated
```

For cutover, run this separately while writers are still stopped:

```bash
bash rotate-key.sh files cutover "${files[@]}"
```

Before restarting, confirm that the replacement key decrypts the promoted originals:

```bash
bash rotate-key.sh files check "${files[@]}"
```

If the data is staged at a different path, pass `--source-data-dir` with the token-reference prefix used by the app. Pass `--config-dir` if runtime config is not under `data/config`. The command inherits `OPENRAG_TENANT_ID` or defaults to `openrag`. No `OLD_*_DIR` exports are needed. With the default prompts, `MIGRATION_DIR` is only for the keys; `.backup` and `.migrated` still go beside the input files.

You can still supply protected files explicitly with `--old-key-file` and `--new-key-file`. If you use explicit key files, `MIGRATION_DIR` is not required. After both keys are securely stored for cutover and rollback, `bash rotate-key.sh cleanup keys` removes the temporary key files after confirmation.

Cutover does not change keys or restart services. Use it only where you can switch the key separately; the Kubernetes Operator rejects in-place key changes. The two file replacements are not atomic together. If interrupted, keep writers stopped and restore both backups with the matching old key. Keep a separate recoverable backup as well: sibling copies are on the same storage and are not a disaster-recovery backup.
