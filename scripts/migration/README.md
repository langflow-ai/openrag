# OpenRAG encryption key rotation

Copy this folder to the migration host. No OpenRAG checkout is needed. This guide covers file migration for `openrag.db` and `connections.json` only. For other layouts, see the [production runbook](https://github.com/langflow-ai/openrag/blob/main/docs/docs/reference/rotate-encryption-key.mdx).

## 1. Requirements and setup

Have the current `OPENRAG_ENCRYPTION_KEY`, access to IBM Cloud Secrets Manager, and OpenSSL. If you haven't provisioned a replacement key yet, generate one in a private, unrecorded terminal:

```bash
openssl rand -base64 32
```

Save the exact output as a **new** secret in IBM Cloud Secrets Manager before cutover. Keep the current secret for rollback; do not overwrite it. Paste the replacement value into `prepare.sh` when prompted in step 2. The migration scripts do not generate a key or change any deployment secrets.

Use Python 3.13 (the OpenRAG-supported version). From the copied folder, create an isolated environment before stopping writers:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export MIGRATION_PYTHON="$PWD/.venv/bin/python"
```

## 2. Set the paths and enter both keys

Use this mode only for a SQLite deployment where `openrag.db` and `connections.json` share a directory and are the only files that need rotation. It refuses `config.yaml`, discovered OAuth caches, and legacy state files; use the full restore workflow for those layouts. Keep writers stopped from backup through cutover, and checkpoint SQLite so no journal, WAL, or SHM files remain.

`prepare.sh` creates a private workspace and prompts for the current and replacement keys without echoing them. It does not generate a key, back up data, or overwrite existing key files. The replacement key must be Base64 for exactly 32 bytes.

```bash
DATA=/app/backend-data  # For a rehearsal, use the restored copy instead.
export MIGRATION_DIR="$DATA/.openrag-keys"
bash prepare.sh
```

The key files are plaintext with restricted permissions. Do not include `.openrag-keys` in data backups, snapshots, or support bundles.

## 3. Back up the files and run preflight

From the migration folder, with OpenRAG writers stopped, run:

```bash
bash rotate-key.sh files backup \
  --sqlite "$DATA/openrag.db" \
  --connections "$DATA/connections.json"
```

If backup succeeds, run the dry-run with the same original paths, not the `.backup` copies:

```bash
bash rotate-key.sh files dry-run \
  --sqlite "$DATA/openrag.db" \
  --connections "$DATA/connections.json"
```

Review the ciphertext counts before proceeding. Stop on any error or unexpected count.

| Command | What changes |
| --- | --- |
| `bash prepare.sh` | Prompts for both keys and saves protected `keys/old` and `keys/new` files. Does not modify application data or existing keys. |
| `files backup` | Creates `openrag.db.backup` and `connections.json.backup` beside the originals. Requires no keys and never overwrites a backup. |
| `files dry-run` | Checks the old key and reports ciphertext counts without writing files. |
| `files apply` | Uses the existing backups after checking they still match the originals. If neither backup exists, creates both. Writes and verifies the two `.migrated` files and their verification receipt; does not replace the originals. |
| `files check` | Decrypts and authenticates the specified files using the saved replacement key. Add `--migrated` to check their `.migrated` siblings instead, or `--key-file PATH` to use a different key. Does not modify either set. |
| `files cutover` | Re-verifies the migrated files, checks that the originals still match the backups, and asks you to confirm. Replaces only the two specified originals. Keeps both sets of sibling copies. |

Backups are **files**, not a backup directory: for example, `/app/backend-data/openrag.db.backup` and `/app/backend-data/connections.json.backup`. The wrapper prints progress and artifact paths to stderr and ciphertext counts to stdout. It never prints key values or decrypted data.

Temporary working copies are staged in private subdirectories beside the inputs and removed when each command exits normally. Make sure that volume has room for the backups, migrated files, and working copies; it does not need a separate writable `/tmp`.

## 4. Rotate and verify the copies

Confirm the old key is recoverable before applying.

```bash
bash rotate-key.sh files apply \
  --sqlite "$DATA/openrag.db" \
  --connections "$DATA/connections.json"
```

If apply succeeds, check the migrated copies with the replacement key:

```bash
bash rotate-key.sh files check \
  --sqlite "$DATA/openrag.db" \
  --connections "$DATA/connections.json" \
  --migrated
```

## 5. Cut over and check the original paths

For cutover, run this separately while writers are still stopped. Skip this step during rehearsal or on an existing Kubernetes Operator-managed instance.

On Linux, cutover preserves and checks NFSv4 ACLs (`system.nfs4_acl`) on both the staged replacements and the rollback copies. It stops before replacing either original if it cannot preserve the permissions or encounters an unsupported ACL.

```bash
bash rotate-key.sh files cutover \
  --sqlite "$DATA/openrag.db" \
  --connections "$DATA/connections.json"
```

Before restarting, confirm that the replacement key decrypts the promoted originals:

```bash
bash rotate-key.sh files check \
  --sqlite "$DATA/openrag.db" \
  --connections "$DATA/connections.json"
```

Configure OpenRAG to use the replacement key before restarting it. Then smoke-test the deployment before reopening traffic.

## 6. Keep backups and clean up the keys

If the data is staged at a different path, pass `--source-data-dir` with the token-reference prefix used by the app. Pass `--config-dir` if runtime config is not under `data/config`. The command inherits `OPENRAG_TENANT_ID` or defaults to `openrag`. No `OLD_*_DIR` exports are needed. With the default prompts, `MIGRATION_DIR` is only for the keys; `.backup` and `.migrated` still go beside the input files.

You can still supply protected files explicitly with `--old-key-file` and `--new-key-file`. If you use explicit key files, `MIGRATION_DIR` is not required. After both keys are securely stored for cutover and rollback, `bash rotate-key.sh cleanup keys` removes the temporary key files after confirmation.

Cutover does not change keys or restart services. Use it only where you can switch the key separately; the Kubernetes Operator rejects in-place key changes. The two file replacements are not atomic together. If interrupted, keep writers stopped and restore both backups with the matching old key. Keep a separate recoverable backup as well: sibling copies are on the same storage and are not a disaster-recovery backup.
