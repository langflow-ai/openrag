# Runbook: rotate `OPENRAG_ENCRYPTION_KEY` for an OpenRAG backend (any tenant namespace)

Rotates the backend encryption key of one OpenRAG tenant deployment on Kubernetes, using the Python CLI [`rotate_encryption_key.py`](rotate_encryption_key.py) (`check`, `apply-to-copy`, `verify`) on an isolated copy of the data. Expect about 15 minutes of backend downtime.

The runbook only needs the tenant namespace. It discovers the deployment, the data volume, the key secret, the data and config paths, and the tenant id from the cluster.

**Scope**

- Covers: SQLite (`openrag.db`) deployments where the data directory is on a PVC mounted into the backend, with `connections.json`, OAuth token caches, and an optional `config/config.yaml`.
- Does not cover: PostgreSQL (`DATABASE_URL` set; step 1 stops), `LANGFLOW_SECRET_KEY` and Langflow data (a separate key; keep it unchanged), OpenSearch.
- Operator-managed deployments: if the backend Deployment is owned by an `OpenRAG` custom resource, the Operator rejects in-place key changes and will report `OPENRAG_ENCRYPTION_KEY value mismatch`. It may also rebuild the key secret from its own state and undo step 9. Use this runbook on an Operator-managed instance only in a development environment, with the owners' agreement. For production, follow [the reference procedure](../../docs/docs/reference/rotate-encryption-key.mdx): run a new instance with new key material and the verified data.

**Rules**

- Keys only ever go in through a hidden prompt, a pipe, or stdin. Never put a key in a command argument or in shell history, and never print one.
- Stop on any error or unexpected count. Never retry on a copy where `apply-to-copy` failed; start again from step 6.
- Use `rotate_encryption_key.py` from the same OpenRAG version as the deployment, or newer. The files in this folder were tested on image `release-saas-0.8.1`.
- Commands work in bash and zsh. Do not use `read -p`; zsh treats `-p` as "coprocess" and the key is silently not read.
- You need on your workstation: `kubectl` with permission to scale the Deployment, create pods, and patch the key secret in the tenant namespace; `python3`; and a checkout of this folder.

## 0. Set up your terminal

Run this in every new terminal. The only value you provide is the tenant namespace.

```bash
export NS=<tenant-namespace>
export STAMP=$(date +%F)
export TOOLS=$(umask 077; mktemp -d)        # private scratch dir on your workstation
```

Create the discovery helper. It is read-only and has three modes:

```bash
cat > $TOOLS/discover.py <<'DISCOVER_PY'
import json, os, shlex, sys

KEY_SETTINGS = {"OPENRAG_DATA_PATH", "OPENRAG_CONFIG_PATH", "OPENRAG_TENANT_ID",
                "OPENRAG_ENCRYPTION_KEY", "DATABASE_URL"}


def emit(values):
    for k, v in values.items():
        print(f"export {k}={shlex.quote(str(v))}")


def analyse(path):
    items = json.load(open(path))["items"]
    if len(items) != 1:
        sys.exit("STOP: expected exactly one backend deployment, found %d" % len(items))
    d = items[0]
    spec = d["spec"]["template"]["spec"]
    c = next((x for x in spec["containers"] if x["name"] == "backend"), None)
    if c is None:
        sys.exit("STOP: no container named 'backend'")
    vols = {v["name"]: v for v in spec.get("volumes", [])}
    mounts = c.get("volumeMounts", [])
    pvc = [m for m in mounts if "persistentVolumeClaim" in vols.get(m["name"], {})]
    env = [m for m in mounts if "secret" in vols.get(m["name"], {})
           and m["mountPath"].endswith("/.env") and m.get("subPath")]
    if len(pvc) != 1 or len(env) != 1:
        sys.exit("STOP: expected one PVC mount and one secret-backed .env mount on the backend container")
    return d, spec, c, vols, pvc[0], env[0]


mode = sys.argv[1]
if mode == "deploy":
    d, spec, c, vols, pvc, env = analyse(sys.argv[2])
    clash = sorted({e["name"] for e in c.get("env", [])} & KEY_SETTINGS)
    if clash:
        sys.exit("STOP: set in the Deployment env, not only in .env: " + ", ".join(clash))
    if c.get("envFrom"):
        print("WARNING: envFrom is set; make sure it does not override the .env settings", file=sys.stderr)
    emit({
        "DEP": d["metadata"]["name"],
        "REPLICAS": d["spec"]["replicas"],
        "IMG": c["image"],
        "PVC": vols[pvc["name"]]["persistentVolumeClaim"]["claimName"],
        "ENV_SECRET": vols[env["name"]]["secret"]["secretName"],
        "ENV_KEY": env["subPath"],
        "SEL": ",".join(f"{k}={v}" for k, v in d["spec"]["selector"]["matchLabels"].items()),
        "OWNER": ",".join(o["kind"] for o in d["metadata"].get("ownerReferences", [])) or "none",
    })
elif mode == "paths":                      # .env arrives on stdin; argv[2] = container working dir
    dot = {}
    keylines = 0
    for line in sys.stdin:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            dot[k] = v.strip().strip('"').strip("'")
            keylines += k == "OPENRAG_ENCRYPTION_KEY"
    if keylines != 1:
        sys.exit("STOP: expected exactly one OPENRAG_ENCRYPTION_KEY line in .env, found %d" % keylines)
    if dot.get("DATABASE_URL"):
        sys.exit("STOP: DATABASE_URL is set (PostgreSQL); this runbook covers SQLite only")

    def path(key, default):
        p = dot.get(key) or default
        return os.path.normpath(p if os.path.isabs(p) else os.path.join(sys.argv[2], p))

    emit({"DATA": path("OPENRAG_DATA_PATH", "data"),
          "CFG": path("OPENRAG_CONFIG_PATH", "config"),
          "TENANT": dot.get("OPENRAG_TENANT_ID") or "openrag"})
elif mode == "helper":                     # argv: dep.json, helper pod name
    d, spec, c, vols, pvc, env = analyse(sys.argv[2])
    pod = {
        "apiVersion": "v1", "kind": "Pod", "metadata": {"name": sys.argv[3]},
        "spec": {
            "restartPolicy": "Never",
            "securityContext": spec.get("securityContext", {}),
            "containers": [{
                "name": "tools", "image": c["image"], "command": ["sleep", "7200"],
                "securityContext": c.get("securityContext", {}),
                "resources": {"requests": {"cpu": "250m", "memory": "512Mi"},
                              "limits": {"cpu": "1", "memory": "1Gi"}},
                "volumeMounts": [{"name": "data", "mountPath": pvc["mountPath"]},
                                 {"name": "tmp", "mountPath": "/tmp"}],
            }],
            "volumes": [
                {"name": "data", "persistentVolumeClaim":
                    {"claimName": vols[pvc["name"]]["persistentVolumeClaim"]["claimName"]}},
                {"name": "tmp", "emptyDir": {}},
            ],
        },
    }
    for k in ("serviceAccountName", "imagePullSecrets", "tolerations", "nodeSelector",
              "affinity", "priorityClassName"):
        if k in spec:
            pod["spec"][k] = spec[k]
    print(json.dumps(pod))
else:
    sys.exit("usage: discover.py deploy|paths|helper ...")
DISCOVER_PY
```

## 1. Preflight (backend still running)

```bash
kubectl -n $NS get deploy -l app.kubernetes.io/component=be -o json > $TOOLS/dep.json
python3 $TOOLS/discover.py deploy $TOOLS/dep.json > $TOOLS/dep.env && . $TOOLS/dep.env
export H=${DEP}-rotation                 # helper pod name
P=$(kubectl -n $NS get pod -l "$SEL" -o name | head -1); echo "backend pod: $P"
WORKDIR=$(kubectl -n $NS exec $P -c backend -- pwd)
kubectl -n $NS get secret $ENV_SECRET -o go-template='{{index .data "'"$ENV_KEY"'"}}' | base64 -d \
  | python3 $TOOLS/discover.py paths "$WORKDIR" > $TOOLS/paths.env && . $TOOLS/paths.env
echo "deployment=$DEP replicas=$REPLICAS image=$IMG"
echo "volume claim=$PVC  key secret=$ENV_SECRET ($ENV_KEY)  owner=$OWNER"
echo "data dir=$DATA  config dir=$CFG  tenant=$TENANT"
```

- If any command prints `STOP:`, do not continue. Typical causes: more than one backend Deployment, PostgreSQL in use, or a setting that lives in the Deployment `env` instead of the `.env` secret.
- If no Deployment is found, check the label: the backend Deployment of an Operator-managed tenant carries `app.kubernetes.io/component=be`. Use `kubectl -n $NS get deploy --show-labels` and adjust the `-l` selector.
- Write down `REPLICAS`. You restore it in step 10.
- If `OWNER` is `OpenRAG`, read the Operator note under **Scope** first.
- The data inventory runs in step 4, once the helper pod exists.

## 2. Get the keys

1. **New key.** Generate a Base64 key for 32 bytes in a private terminal and store it in your secrets manager before you cut over:
   ```bash
   openssl rand -base64 32
   ```
2. **Old key.** It is the key the backend uses now, in the `.env` of `$ENV_SECRET`. Store it in your secrets manager too. Step 6 pipes it into the helper without printing it, so you do not need to type it.

Do not copy a key from the Operator's key secret, if there is one. It can differ from the key the pod actually uses.


## 2.1 Adding the Newly Generated Key to IBM Cloud Secrets Manager

Before proceeding with the key rotation, ensure that you have a backup of the existing encryption key. This is required in case a rollback is needed.

1. Use the replacement key generated in Step 2 of the migration procedure.

2. Navigate to **IBM Cloud Secrets Manager** and search for the relevant **Instance ID**.

3. Locate the secret named `<uuid>--openrag-encryption-key` in the search results.

4. Click the secret to open its details in the side panel.

5. Click **Actions** in the top-right corner of the side panel to open the menu.

6. Select **Rotate** from the menu.

7. In the **Secret value** section, select **Enter value** and paste the newly generated key into the input field.

8. Click the blue **Rotate** button to complete the rotation.

The replacement encryption key is now stored in IBM Cloud Secrets Manager.


## 3. Stop the backend

```bash
kubectl -n $NS scale deploy/$DEP --replicas=0
kubectl -n $NS wait --for=delete pod -l "$SEL" --timeout=180s
kubectl -n $NS get deploy $DEP        # 0/0; check again after a minute that it stays at 0
```

If something scales it back up, stop and pause that controller with its owners. The data volume is single-attach, so the helper cannot start while the backend runs.

## 4. Start the helper pod

The helper runs the backend image with the backend's own security context, node placement, and service account, plus the data volume and an empty `/tmp`. Nothing else is mounted.

```bash
python3 $TOOLS/discover.py helper $TOOLS/dep.json $H | kubectl -n $NS create -f -
kubectl -n $NS wait --for=condition=Ready pod/$H --timeout=240s
hx() { kubectl -n $NS exec -i $H -c tools -- "$@"; }
hx python3 -c "import cryptography, sqlalchemy, aiosqlite, yaml; print('python deps ok')"
```

The image has no `tar`, so the commands below use Python. Copy the migration scripts and the file helper into the helper pod. Run this from the `scripts/migration/` folder of your checkout:

```bash
tar -cf - rotate_encryption_key.py rotation_paths.py \
  | hx python3 -c 'import sys,tarfile,os;os.makedirs("/tmp/migration",exist_ok=True);tarfile.open(fileobj=sys.stdin.buffer,mode="r|").extractall("/tmp/migration")'
hx sh -c 'cat > /tmp/rot.py' <<'ROT_PY'
"""Inventory, backup, work-copy, promote and restore helper for the key-rotation runbook.

Environment: DATA (data dir), CFG (config dir), optional WORK (default /tmp/work).
Usage: rot.py inventory | tar | copy DEST | workcopy | promote | restore DIR
"""
import glob, json, os, shutil, sqlite3, sys, tarfile

DATA, CFG = os.environ["DATA"], os.environ["CFG"]
WORK = os.environ.get("WORK", "/tmp/work")
PATTERNS = ("google_drive_*.json", "onedrive_*.json", "sharepoint_*.json",
            "conversations.json", "session_ownership.json")


def die(msg):
    sys.exit("STOP: " + msg)


def files():
    names = ["connections.json"] if os.path.isfile(os.path.join(DATA, "connections.json")) else []
    for pat in PATTERNS:
        names += sorted(os.path.basename(p) for p in glob.glob(os.path.join(DATA, pat))
                        if not p.endswith(".backup"))
    return names


def config_rel():
    rel = os.path.relpath(CFG, DATA)
    if rel == ".":
        die("config dir equals data dir - unsupported layout")
    if rel.startswith(".."):
        if os.path.exists(os.path.join(CFG, "config.yaml")):
            die("config.yaml is outside the data volume - ask the owner")
        return None
    return rel if os.path.isdir(CFG) else None


def require_offline_db():
    if not os.path.isfile(os.path.join(DATA, "openrag.db")):
        die("openrag.db not found in the data dir")
    for s in ("-wal", "-shm", "-journal"):
        if os.path.exists(os.path.join(DATA, "openrag.db" + s)):
            die("SQLite sidecar present: openrag.db" + s)


def snapshot_db(dest):
    src = sqlite3.connect("file:" + os.path.join(DATA, "openrag.db") + "?mode=ro", uri=True)
    dst = sqlite3.connect(dest)
    src.backup(dst)
    dst.close()
    src.close()


def inventory():
    require_offline_db()
    print("data dir:", DATA, "| config dir:", CFG, "| config present:", config_rel())
    for n in ["openrag.db"] + files():
        print(f"  {n}  {os.path.getsize(os.path.join(DATA, n))} bytes")
    doc = json.load(open(os.path.join(DATA, "connections.json")))
    recs = doc["connections"] if isinstance(doc, dict) else doc
    print("connections:", len(recs))
    if not recs:
        print("WARNING: connections.json lists no connections - restore it before rotating if that is unexpected")
    for r in recs:
        tf = (r.get("config") or {}).get("token_file")
        if not tf:
            continue
        where = "ok" if os.path.isfile(tf) else "MISSING (counts as 'absent OAuth cache paths')"
        inside = os.path.abspath(tf).startswith(os.path.abspath(DATA) + os.sep)
        print(f"  token_file {tf}: {where}{'' if inside else '  <-- outside the data dir: needs --map-token-cache'}")


def tar_out():
    require_offline_db()
    names = ["openrag.db"] + files() + ([config_rel()] if config_rel() else [])
    os.chdir(DATA)
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as t:
        for n in names:
            t.add(n)
    print("\n".join(names), file=sys.stderr)


def copy(dest):
    require_offline_db()
    dest = os.path.join(DATA, dest)
    os.makedirs(dest, mode=0o700)          # fails if it exists: never overwrites
    for n in files():
        shutil.copy2(os.path.join(DATA, n), dest)
    if config_rel():
        shutil.copytree(CFG, os.path.join(dest, "config"))
    snapshot_db(os.path.join(dest, "openrag.db"))
    for f in sorted(os.listdir(dest)):
        print(f, os.path.getsize(os.path.join(dest, f)))


def workcopy():
    require_offline_db()
    shutil.rmtree(WORK, ignore_errors=True)
    for sub in ("data", "config", "keys"):
        os.makedirs(os.path.join(WORK, sub), mode=0o700)
    os.chmod(WORK, 0o700)
    snapshot_db(os.path.join(WORK, "data", "openrag.db"))
    for n in files():
        shutil.copy2(os.path.join(DATA, n), os.path.join(WORK, "data"))
    if config_rel():
        shutil.copytree(CFG, os.path.join(WORK, "config"), dirs_exist_ok=True)
    for r, _, fs in os.walk(WORK):
        for f in sorted(fs):
            print(os.path.join(r, f), os.path.getsize(os.path.join(r, f)))


def put_back(src_dir, label):
    for f in sorted(os.listdir(src_dir)):
        if f == "config":
            continue
        tmp = os.path.join(DATA, ".new." + f)
        shutil.copy2(os.path.join(src_dir, f), tmp)
        os.replace(tmp, os.path.join(DATA, f))
        print(label, f)


def promote():
    put_back(os.path.join(WORK, "data"), "promoted")
    cfg = os.path.join(WORK, "config", "config.yaml")
    if os.path.isfile(cfg):
        tmp = os.path.join(CFG, ".new.yaml")
        shutil.copy2(cfg, tmp)
        os.replace(tmp, os.path.join(CFG, "config.yaml"))
        print("promoted config.yaml")


def restore(src):
    src = os.path.join(DATA, src)
    if not os.path.isfile(os.path.join(src, "openrag.db")):
        die("no openrag.db in " + src)
    put_back(src, "restored")
    cfg = os.path.join(src, "config", "config.yaml")
    if os.path.isfile(cfg):
        tmp = os.path.join(CFG, ".new.yaml")
        shutil.copy2(cfg, tmp)
        os.replace(tmp, os.path.join(CFG, "config.yaml"))
        print("restored config.yaml")


cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "inventory":
    inventory()
elif cmd == "tar":
    tar_out()
elif cmd == "copy" and len(sys.argv) == 3:
    copy(sys.argv[2])
elif cmd == "workcopy":
    workcopy()
elif cmd == "promote":
    promote()
elif cmd == "restore" and len(sys.argv) == 3:
    restore(sys.argv[2])
else:
    sys.exit(__doc__)
ROT_PY
rot() { hx env DATA="$DATA" CFG="$CFG" WORK=/tmp/work python3 /tmp/rot.py "$@"; }
rot inventory
```

Read the `inventory` output:

- `connections.json` must list the connections you expect. If it lists none unexpectedly, stop and restore it from a backup first.
- Every `token_file` should say `ok`. A `MISSING` entry only adds one to the `absent OAuth cache paths` count; that connection needs re-authorizing in the UI later, and it does not block the rotation.
- A token path marked `outside the data dir` needs `--map-token-cache STORED_PATH COPY_PATH` in step 7. Stage the file under `/tmp/work/data` first. Ask the owner if you meet this.
- A `STOP:` line (SQLite sidecars, `config.yaml` outside the volume) must be resolved before you go on.

Define `hx` and `rot` again in every new terminal (the two function lines above).

## 5. Back up (rollback set)

**5.1 Snapshot the volume.** Take a snapshot of the PVC `$PVC` with your usual tooling, now that writers are stopped.

**5.2 Copy the files to your workstation.** Run from a private directory:

```bash
mkdir -p ~/openrag-rotation-$NS-$STAMP && chmod 700 ~/openrag-rotation-$NS-$STAMP && cd ~/openrag-rotation-$NS-$STAMP
rot tar > pre-rotation.tar
tar -tvf pre-rotation.tar
```

The file list must contain `openrag.db`, `connections.json`, and every OAuth cache from the inventory. Stop if one is missing. Store the tar with the old key.

**5.3 Make an on-volume copy** (SQLite backup API for the database; refuses to overwrite):

```bash
rot copy pre-rotation-$STAMP
```

The sizes must match step 4's inventory. This copy is your fast rollback source in step 11.

## 6. Make the isolated working copy and load the keys

```bash
rot workcopy
```

- `connections.json` must be non-empty, and every OAuth cache must be present.
- If `config.yaml` exists it is copied and rotated too (`config.yaml providers` appears in the counts).
- If an OAuth cache has another name or location, add `--token-cache <path relative to /tmp/work/data>` to all three commands in step 7.

**Old key.** It comes straight from the secret, so you never type or see it:

```bash
kubectl -n $NS get secret $ENV_SECRET -o go-template='{{index .data "'"$ENV_KEY"'"}}' | base64 -d \
  | grep '^OPENRAG_ENCRYPTION_KEY=' | cut -d= -f2- | hx sh -c 'umask 077; cat > /tmp/work/keys/old'
```

**New key.** Paste it at the hidden prompt:

```bash
printf 'NEW key: ' >&2; IFS= read -rs K; echo >&2
printf '%s\n' "$K" | hx sh -c 'umask 077; cat > /tmp/work/keys/new'; unset K
```

**Check the key files without printing them:**

```bash
hx sh -c 'for f in old new; do printf "%s: %s bytes, %s lines, hash %s\n" $f $(wc -c < /tmp/work/keys/$f) $(wc -l < /tmp/work/keys/$f) $(tr -d "\n" < /tmp/work/keys/$f | sha256sum | cut -c1-12); done; ls -l /tmp/work/keys'
```

- `new` must show `45 bytes, 1 lines` (44 Base64 characters plus the newline). Any other size means the key is not Base64 for 32 bytes.
- `old` must be 1 line and more than 1 byte.
- The two hashes must differ. Both files must be mode `-rw-------`.

## 7. Check, rotate, verify (on the copy)

```bash
hx env DATA="$DATA" CFG="$CFG" TENANT="$TENANT" sh -c '
set -e
W=/tmp/work; M=/tmp/migration
C="--data-dir $W/data --config-dir $W/config --sqlite $W/data/openrag.db --source-data-dir $DATA --tenant-id $TENANT"
echo "### 1 check (old key, read-only)"; python3 $M/rotate_encryption_key.py check $C --old-key-file $W/keys/old --new-key-file $W/keys/new
echo "### 2 apply-to-copy";              python3 $M/rotate_encryption_key.py apply-to-copy $C --original-data-dir "$DATA" --original-config-dir "$CFG" --old-key-file $W/keys/old --new-key-file $W/keys/new
echo "### 3 verify (new key only)";      env -u OPENRAG_ENCRYPTION_KEY python3 $M/rotate_encryption_key.py verify $C --key-file $W/keys/new
'
```

**Pass criteria**

- All three commands print `succeeded`.
- The counts in `check` and `verify` are identical. Compare them with what you expect: users, workspace settings, OAuth caches (plus `absent OAuth cache paths` for any missing cache), and connector secrets.
- No `No ciphertext found` line.

**If it fails**

- `unreadable encryption envelope`: the old key is wrong, or part of the data is already on a different key. Stop and find out which before doing anything else.
- `tenant mismatch`: the tenant id is wrong. It comes from `OPENRAG_TENANT_ID` in `.env`, otherwise `openrag`.
- Any `apply-to-copy` failure: discard the copy and repeat step 6 (`rot workcopy`, then reload both keys).

## 8. Promote the rotated files

The backend stays stopped. Each file is staged under a temporary name and then renamed over the original.

```bash
rot promote
hx ls -l --time-style=full-iso "$DATA"
```

- The owner and mode must match what the files had before (compare with the inventory and the backup).
- There must be no `openrag.db-wal`, `-shm`, or `-journal` files.

Verify the real files, using only the new key:

```bash
hx env DATA="$DATA" CFG="$CFG" TENANT="$TENANT" sh -c '
CD=$CFG; [ -d "$CD" ] || CD=/tmp/work/config
env -u OPENRAG_ENCRYPTION_KEY python3 /tmp/migration/rotate_encryption_key.py verify --data-dir "$DATA" --config-dir "$CD" --sqlite "$DATA/openrag.db" --source-data-dir "$DATA" --tenant-id "$TENANT" --key-file /tmp/work/keys/new'
```

The counts must match step 7.

## 9. Switch the backend to the new key

The backend reads the key from the `.env` entry of `$ENV_SECRET`. Define the function once; it takes the key on stdin, rewrites only the `OPENRAG_ENCRYPTION_KEY` line, and never prints it. Pass `--dry-run=server` as an argument to test without changing anything:

```bash
put_key() {
  local D; D=$(umask 077; mktemp -d) || return 1
  kubectl -n $NS get secret $ENV_SECRET -o go-template='{{index .data "'"$ENV_KEY"'"}}' | base64 -d > "$D/env"
  cat > "$D/patch.py" <<'PATCH_PY'
import base64, json, sys
env_file, secret_key = sys.argv[1], sys.argv[2]
new = sys.stdin.read().strip()
lines = open(env_file).read().splitlines()
hits = [i for i, l in enumerate(lines) if l.startswith("OPENRAG_ENCRYPTION_KEY=")]
if len(hits) != 1 or not new or "\n" in new:
    sys.exit("ERROR: expected exactly one OPENRAG_ENCRYPTION_KEY line and one non-empty key")
lines[hits[0]] = "OPENRAG_ENCRYPTION_KEY=" + new
print(json.dumps({"data": {secret_key: base64.b64encode(("\n".join(lines) + "\n").encode()).decode()}}))
PATCH_PY
  python3 "$D/patch.py" "$D/env" "$ENV_KEY" > "$D/patch.json" || { rm -rf "$D"; return 1; }
  kubectl -n $NS patch secret $ENV_SECRET --type merge --patch-file "$D/patch.json" "$@"
  local rc=$?; rm -rf "$D"; return $rc
}
```

Test it, then apply it:

```bash
hx cat /tmp/work/keys/new | put_key --dry-run=server     # prints "secret/<name> patched (server dry run)"
hx cat /tmp/work/keys/new | put_key                      # applies the change
```

Check that the secret now holds the new key. The two hashes must match:

```bash
kubectl -n $NS get secret $ENV_SECRET -o go-template='{{index .data "'"$ENV_KEY"'"}}' | base64 -d | grep '^OPENRAG_ENCRYPTION_KEY=' | cut -d= -f2- | tr -d '\n' | shasum -a 256 | cut -c1-12
hx sh -c "tr -d '\n' < /tmp/work/keys/new | sha256sum | cut -c1-12"
```

If the Operator reverts this patch on its next reconcile, the backend would restart on the old key and the rotated data would be unreadable. See the note under **Scope**.

## 10. Restart and smoke test

```bash
kubectl -n $NS delete pod $H                 # releases the volume and wipes /tmp/work, including the key files
kubectl -n $NS scale deploy/$DEP --replicas=$REPLICAS
kubectl -n $NS rollout status deploy/$DEP --timeout=300s
P=$(kubectl -n $NS get pod -l "$SEL" -o name | head -1)
kubectl -n $NS logs $P -c backend --tail=5000 | grep -iE 'Failed to decrypt|unreadable|Cannot decrypt|Skipping stored connection' || echo "no decrypt errors"
kubectl -n $NS logs $P -c backend --tail=5000 | grep 'Loaded persisted connector connections'
```

The `loaded_count` must equal the number of connections from the step 4 inventory. Then check in the UI:

- Sign in and open your profile and preferences.
- Run a chat with a model that uses a stored provider key.
- Sync an existing connector, or refresh its token.
- Confirm `connections.json` still lists your connections.

## 11. Rollback

If any check fails:

1. Stop the backend: `kubectl -n $NS scale deploy/$DEP --replicas=0`, and wait for the pod to go (step 3).
2. Start a helper pod (step 4: only the pod creation and the `rot.py` copy are needed) and define `hx` and `rot`.
3. Restore the data as a unit: `rot restore pre-rotation-$STAMP`. If you lost the on-volume copy, restore from the step 5.2 tar or the PVC snapshot.
4. Put the old key back with the step 9 function. Take it from your secrets manager and paste it at a hidden prompt, never on the command line:
   ```bash
   printf 'OLD key: ' >&2; IFS= read -rs K; echo >&2
   printf '%s\n' "$K" | put_key; unset K
   ```
5. Delete the helper, scale the backend back to `$REPLICAS`, and repeat the smoke test.

Never run old data with the new key, or rotated data with the old key. Keep the old key and the backups until your rollback window closes.


## 12. Recreate the Cluster Secret

A mismatch between the cluster secret and the encryption key configured in the `openrag-be-env` Secret (patched in Step 9) can cause OpenRAG failures.

To recreate the cluster secret and ensure both secrets contain the same encryption key, follow these steps:

1. **Scale down the `intermediate-openrag-operator** to prevent reconciliation while deleting the secret.

   ```bash
   kubectl scale deployment intermediate-openrag-operator \
     --replicas=0 -n openrag-control
   ```

2. **Delete the existing cluster secret.**

   ```bash
   kubectl delete secret c-<uuid>-openrag-encryption-key -n <namespace>
   ```

   If the secret remains stuck in `Terminating`, remove its finalizers:

   ```bash
   kubectl patch secret c-<uuid>-openrag-encryption-key -n <namespace> \
     --type=merge -p '{"metadata":{"finalizers":[]}}'
   ```

3. **Scale the operator back up** once the old secret has been deleted.

   ```bash
   kubectl scale deployment intermediate-openrag-operator \
     --replicas=1 -n openrag-control
   ```

4. **Verify that the new cluster secret is created.**

   The operator should recreate the `c-<uuid>-openrag-encryption-key` Secret within approximately one minute. Verify that the encryption key in the newly created cluster secret matches the key configured in `openrag-be-env`.

   ```bash
   kubectl get secret openrag-be-env -n <namespace> \
     -o jsonpath='{.data.<key>}' | base64 -d | grep -i encrypt

   kubectl get secret c-<uuid>-openrag-encryption-key -n <namespace> \
     -o jsonpath='{.data.<key>}' | base64 -d
   ```

5. **Restart the OpenRAG backend.**

   Once the new cluster secret is created and the encryption keys are confirmed to match, restart the `openrag-be` deployment:

   ```bash
   kubectl rollout restart deployment openrag-be -n <namespace>
   ```

   Verify that the backend pods come up successfully and OpenRAG is functioning as expected.

## 13. Cleanup

- Delete the helper pod if it still exists: `kubectl -n $NS delete pod $H --ignore-not-found`. This also wipes `/tmp/work` with both key files.
- On your workstation: `rm -rf "$TOOLS"`, and move `pre-rotation.tar` into controlled storage together with the old key.
- On the volume: keep `pre-rotation-$STAMP/` until the rollback window closes, then delete it. Exclude `pre-rotation-*` directories from volume backups. Delete any plaintext key files left on the volume by earlier attempts, for example a `.openrag-keys/` directory, once both keys are in your secrets manager.
- Re-authorize any connection whose OAuth cache was missing (`absent OAuth cache paths` in the counts).
