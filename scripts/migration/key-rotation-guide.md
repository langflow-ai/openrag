# Key rotation guide (OpenRAG tenant on Kubernetes)

High-level starting point for an SRE rotating the two independent encryption keys of one OpenRAG tenant. This guide is an overview only. Run the detailed commands from the linked runbooks.

| Key | Protects | Stored in | Runbook |
| --- | --- | --- | --- |
| Langflow Fernet key (`LANGFLOW_SECRET_KEY`) | Langflow `Credential` global variables (`langflow.db`) | K8s secret `openrag-lf-env`, IBM Secrets Manager `<tenant-namespace>-langflow-fernet-key` | [scripts/migration/langflow/langflow-key-rotation-secure.md](langflow/langflow-key-rotation-secure.md) |
| OpenRAG backend key (`OPENRAG_ENCRYPTION_KEY`) | Backend SQLite data, `connections.json`, OAuth token caches, `config.yaml` provider keys | `.env` entry of the backend key secret | [scripts/migration/full-restore-runbook.md](full-restore-runbook.md) |

The two keys are unrelated. Rotate them one at a time, each in its own change window, and smoke test after each.

## Before you start

- Schedule a maintenance window. Each rotation stops its component: about 15 minutes of backend downtime, and a Langflow restart.
- Confirm `kubectl` access to the tenant namespace, and that the tooling version matches the deployed image (tested on `release-saas-0.8.1`).
- Check for an Operator-managed deployment (backend owned by an `OpenRAG` custom resource). The Operator can revert the key patch. Read the **Scope** note in the full-restore runbook before you continue.
- Check that the backend does not use PostgreSQL (`DATABASE_URL` set). The runbook covers SQLite only.
- Take a snapshot of the data volumes (backend PVC and Langflow data) and a copy of the current keys. Keep them until the rollback window closes.
- Never put a key in a command argument, shell history, ticket, or log. Use hidden prompts, pipes, or stdin.

## A. Rotate the Langflow Fernet key

Follow [scripts/migration/langflow/langflow-key-rotation-secure.md](langflow/langflow-key-rotation-secure.md) in order. It never prints the keys. It passes them through files with mode 600, pipes, and fingerprints:

1. Back up the old key in IBM Secrets Manager (step 1).
2. Extract the old key on the Langflow pod into a private file, and compare fingerprints with the Secrets Manager copy (step 2).
3. Generate the new Fernet key on the pod and store it in your secrets manager (step 3).
4. Copy `langflow/migrate_secret_key.py` onto the Langflow pod (step 4).
5. Run it with `--dry-run` (step 5), then for real (step 6). This re-encrypts the credentials in `langflow.db`.
6. Patch `LANGFLOW_SECRET_KEY` in the `openrag-lf-env` secret and check the fingerprints (step 7).
7. Delete the key files on the pod (step 8), then restart the Langflow deployment (step 9).
8. Verify: open a flow that uses a `Credential` variable and run it. Confirm IBM Secrets Manager holds the new key (step 10).

**Rollback:** see the Rollback section of [scripts/migration/langflow/langflow-key-rotation-secure.md](langflow/langflow-key-rotation-secure.md). Restore the Langflow data volume snapshot, put the old key back in `openrag-lf-env`, and restart.

## B. Rotate the OpenRAG backend encryption key

Follow [scripts/migration/full-restore-runbook.md](full-restore-runbook.md) in order:

1. Run the preflight (steps 0 and 1). It discovers the deployment, volume, secret, and tenant id. Stop on any `STOP:` message.
2. Generate the new key (`openssl rand -base64 32`). Store it and the old key in your secrets manager (step 2).
3. Scale the backend to 0 (step 3) and start the helper pod on the data volume (step 4).
4. Back up: volume snapshot, tar to your workstation, and an on-volume copy (step 5).
5. Make an isolated working copy and load both keys through pipes and hidden prompts (step 6).
6. Run `check`, `apply-to-copy`, and `verify` on the copy (step 7). Counts must match, and all three commands must print `succeeded`.
7. Promote the rotated files, then verify them with the new key only (step 8).
8. Patch `OPENRAG_ENCRYPTION_KEY` in the backend key secret (step 9). Check that the secret hash matches the new key.
9. Delete the helper, scale the backend back to the original replica count, and smoke test (step 10). Check for no decrypt errors, the expected connection count, a chat that uses a stored provider key, and a connector sync.
10. Clean up (step 12). Keep the old key and the backups until the rollback window closes.

**Rollback (step 11 of [scripts/migration/full-restore-runbook.md](full-restore-runbook.md)):** scale to 0, restore the on-volume copy, tar, or snapshot, put the old key back in the secret, and scale up. Never run old data with the new key, or rotated data with the old key.

## After both rotations

- Confirm both new keys are in the secrets manager and match what the pods use.
- Re-authorize any connection whose OAuth cache was missing (see the runbook counts).
- Record the rotation date, operator, and keys' secrets-manager versions in your change record. Schedule the next rotation.
