# Rotate Langflow Fernet Key (IBM Cloud / OpenRag SaaS), without printing the key

Same procedure as [langflow-key-rotation.md](langflow-key-rotation.md), changed so that neither the old nor the new Fernet key is ever printed, typed into a command, or left in shell history. Keys travel only through files with mode 600, pipes, and command substitution. Fingerprints (the first 12 hex characters of a SHA-256) replace visual comparison.

The Langflow 'Fernet' key is used to store Langflow global variables of type 'Credential' in the Langflow sqlite database. After Fernet key-rotation, any Langflow Flows that use encrypted credentials should continue to work.

**Rules**

- Never run `cat`, `echo`, or `printenv` on a key, and never paste a key into a command. Do not enable `set -x`.
- The key files live in the fixed directory `/tmp/lf-key-rotation`. Every pod-shell step below starts by setting `K=/tmp/lf-key-rotation`, so you can exit and re-enter the pod shell between steps. The files survive as long as the pod is not restarted or recreated. If the pod restarts before step 6 finishes, the new key file is lost: start again from step 2.
- `migrate_secret_key.py` takes keys only as `--old-key` and `--new-key` arguments, and prints the new key in one line of its output. The commands below hide that line with `grep -v`. While the script runs, the keys are visible in the pod's process list to anyone who can run `ps` in that container.

## 1. Back up the existing (old) Fernet key in IBM Secrets Manager

IBM Secret Manager / Secret Name:
```
<OPENRAG_TENANT_NAMESPACE>-langflow-fernet-key
```

Confirm the backup exists and is the current version. Do not display its value.

## 2. Extract the actual (old) Fernet key on the Langflow pod, without printing it

Shell into the Langflow pod, create a private scratch directory, and write the old key into it:

```
K=/tmp/lf-key-rotation
(umask 077; mkdir "$K") || echo "STOP: $K already exists; see step 8 to remove it first"
grep '^LANGFLOW_SECRET_KEY=' /app/.env | cut -d= -f2- | tr -d '\n' > $K/old
ls -l $K/old
tr -d '\n' < $K/old | sha256sum | cut -c1-12
```

The file must be mode `-rw-------` and not empty. Compare the fingerprint with the one for the Secrets Manager copy, computed on your workstation without displaying the key (pipe the secret value into `shasum -a 256 | cut -c1-12`). The two must match. If they differ, stop.

## 3. Generate the new Fernet key into a file

In the pod shell:

```
K=/tmp/lf-key-rotation
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode(), end="")' > $K/new
chmod 600 $K/new
tr -d '\n' < $K/new | sha256sum | cut -c1-12
```

The two fingerprints (old and new) must differ.

Store the new key in IBM Secrets Manager now, before you migrate: the new key must exist outside the pod before the data depends on it. On your workstation, pipe it straight from the pod into your Secrets Manager tooling, for example:

```
kubectl -n <TENANT_NAMESPACE> exec <OPENRAG_LF_POD_NAME> -- cat /tmp/lf-key-rotation/new | <your secrets manager command that reads the value from stdin>
```

Store it as a new version of the secret in step 1, or as a pending version if your policy requires it.

## 4. Copy the migrate_secret_key.py script onto the Langflow pod

On your workstation:

```
kubectl cp migrate_secret_key.py <REPLACE_WITH_OPENRAG_LF_POD_NAME>:/app/langflow-data/migrate_secret_key.py
```

## 5. Execute a Dry-Run of the Langflow DB migration

In the pod shell. The keys are read from the files and the line that echoes the new key is removed from the output:

```
K=/tmp/lf-key-rotation
cd /app/langflow-data

uv run python migrate_secret_key.py \
  --dry-run \
  --database-url sqlite:////app/data/langflow.db \
  --old-key "$(cat $K/old)" \
  --new-key "$(cat $K/new)" 2>&1 | grep -v 'provided new key'
```

Check that the output reports `Failed: 0` for every step and ends with `DRY RUN COMPLETE`.

## 6. Execute the real Langflow DB migration (with data encrypted with the new key)

In the pod shell:

```
K=/tmp/lf-key-rotation
cd /app/langflow-data

uv run python migrate_secret_key.py \
  --database-url sqlite:////app/data/langflow.db \
  --old-key "$(cat $K/old)" \
  --new-key "$(cat $K/new)" 2>&1 | grep -v 'provided new key'
```

The output must end with `MIGRATION COMPLETE` and `0 failures`. Because of the `grep` pipe, an exit code is not reliable; read the output.

The script also writes the new key to `secret_key` and the old key to `secret_key.backup.*` in its config directory (shown on the `Config dir:` line), both mode 600. Keep the backup until the rollback window closes, and delete it afterwards.

## 7. Update the Kubernetes Secret (openrag-lf-env) with the updated (new) Fernet key

Run the following on your local bash shell. The new key is read from the pod straight into the environment of the `awk` process. It never appears in a command line or on screen:

```
NAMESPACE='<<REPLACE_WITH_OPENRAG_TENANT_NAMESPACE>>'
SECRET_NAME='openrag-lf-env'
LF_POD='<<REPLACE_WITH_OPENRAG_LF_POD_NAME>>'
K_PATH='/tmp/lf-key-rotation'

kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" \
  -o jsonpath='{.data.\.env}' \
  | base64 -d \
  | NEW_SECRET_KEY="$(kubectl -n "$NAMESPACE" exec "$LF_POD" -- cat "$K_PATH/new")" \
    awk '/^LANGFLOW_SECRET_KEY=/ {print "LANGFLOW_SECRET_KEY=" ENVIRON["NEW_SECRET_KEY"]; next} {print}' \
  | jq -Rs '{stringData: {".env": .}}' \
  | kubectl patch secret "$SECRET_NAME" \
      -n "$NAMESPACE" \
      --type=merge \
      --patch-file=/dev/stdin
```

Check that the secret now holds the new key. The two fingerprints must match:

```
kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o jsonpath='{.data.\.env}' | base64 -d \
  | grep '^LANGFLOW_SECRET_KEY=' | cut -d= -f2- | tr -d '\n' | shasum -a 256 | cut -c1-12
kubectl -n "$NAMESPACE" exec "$LF_POD" -- sh -c "tr -d '\n' < $K_PATH/new | sha256sum | cut -c1-12"
```

## 8. Delete the key files on the pod

In the pod shell:

```
K=/tmp/lf-key-rotation
rm -rf "$K"
unset K
```

## 9. Restart the Langflow pod

```
kubectl rollout restart deployment openrag-lf
```

Open a flow that uses a `Credential` variable and run it. Users must log in again.

## 10. Confirm IBM Secrets Manager holds the new Langflow Fernet key

IBM Secret Manager / Secret Name:
```
<OPENRAG_TENANT_NAMESPACE>-langflow-fernet-key
```

The current version must be the new key (stored in step 3). Compare its fingerprint with the fingerprint from step 7, without displaying the value.

## Rollback

If the migration or the smoke test fails, restore the old key from the Secrets Manager backup (step 1) into `openrag-lf-env` with the same piped method as step 7, and restore the Langflow database from your volume snapshot or backup. Never run data encrypted with one key against the other key.
