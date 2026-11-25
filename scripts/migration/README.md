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

Store the current key and your replacement key in separate protected one-line files outside the data directory. The script does not generate a key. The replacement must be Base64 for exactly 32 bytes.

```bash
DATA=/app/backend-data  # Use the actual parent of the two files.
files=(
  --sqlite "$DATA/openrag.db"
  --connections "$DATA/connections.json"
  --new-key-file /secure/keys/new
)

bash rotate-key.sh files dry-run "${files[@]}" --old-key-file /secure/keys/old
```

| Command | What changes |
| --- | --- |
| `files dry-run` | Checks the old key and reports ciphertext counts without writing files. |
| `files apply` | Creates `openrag.db.backup`, `connections.json.backup`, `openrag.db.migrated`, `connections.json.migrated`, and a verification receipt next to the originals. Leaves the original files untouched and never overwrites an existing artifact. |
| `files cutover` | Re-verifies the migrated files, checks that the originals still match the backups, and asks you to confirm. Replaces only the two specified originals. Keeps both sets of sibling copies. |

After reviewing the dry run and confirming the old key is recoverable:

```bash
bash rotate-key.sh files apply "${files[@]}" --old-key-file /secure/keys/old
```

For cutover, run this separately while writers are still stopped:

```bash
bash rotate-key.sh files cutover "${files[@]}"
```

If the data is staged at a different path, pass `--source-data-dir` with the token-reference prefix used by the app. Pass `--config-dir` if runtime config is not under `data/config`. The command inherits `OPENRAG_TENANT_ID` or defaults to `openrag`. It does not need `MIGRATION_DIR` or the `OLD_*_DIR` exports.

Cutover does not change keys or restart services. Use it only where you can switch the key separately; the Kubernetes Operator rejects in-place key changes. The two file replacements are not atomic together. If interrupted, keep writers stopped and restore both backups with the matching old key. Keep a separate recoverable backup as well: sibling copies are on the same storage and are not a disaster-recovery backup.
