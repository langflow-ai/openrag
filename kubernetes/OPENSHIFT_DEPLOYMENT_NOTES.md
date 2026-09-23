# OpenRAG on OpenShift — Deployment Feedback

**Audience:** OpenRAG maintainers (IBM / langflow-ai)
**Context:** Live deployment of OpenRAG to a real OpenShift cluster (IBM TechZone sandbox, OpenShift 4.18.48, OpenShift Data Foundation storage) using the **operator** installation path (`kubernetes/operator` + `kubernetes/helm/operator`). Single-tenant deployment in one dedicated namespace/project (`openrag`), with cluster-admin access.
**Outcome:** Successfully deployed end-to-end — frontend, backend, Langflow, Postgres, OpenSearch, Docling (serve + worker + Valkey queue) — all healthy, chat/search working with real per-user authentication. Getting there required **10 distinct fixes**, none of which are documented anywhere in the repo today. This doc is a full account of what broke, why, and how we fixed it, plus concrete recommendations.

This deployment used **kube:admin**-level access. Several of the fixes below (SCC grants, ClusterRole patches) are things a typical namespace-scoped deployer would not be able to do themselves — worth keeping in mind when prioritizing fixes.

---

## 1. Architecture used

- **Operator pattern**, not the direct Helm chart (`kubernetes/helm/openrag`). The operator (`kubernetes/helm/operator` installs it) watches an `OpenRAG` custom resource and reconciles Deployments/Services/PVCs for frontend, backend, and Langflow.
- Everything — operator, CR-managed app pods, and the components we had to deploy ourselves — lives in **one namespace** (`openrag`) for a clean single-command teardown (`oc delete project openrag`).
- **OpenSearch, PostgreSQL, and Docling are not deployed by the operator or the Helm chart** — both explicitly document this ("OpenSearch is NOT deployed by this operator", same for Docling). We had to deploy all three ourselves. Docling and its Valkey queue *are* operator-manageable via `spec.doclingComponents` (undocumented outside the CRD/sample comments); OpenSearch and Postgres have no such support at all — they're purely "point the CR at an existing endpoint."

## 2. Prerequisites not covered by the repo

| Component | Deployed how | Notes |
|---|---|---|
| **OpenSearch** | Standalone Deployment, `docker.io/langflowai/openrag-opensearch:latest` | **Must** be this exact image (or a rebuild of `Dockerfile` at repo root). The backend hardcodes `engine: jvector` for its `knn_vector` field mapping (`src/utils/embedding_fields.py:158`), and `jvector` is a custom OpenSearch plugin only present in this image (built from `opensearch-project/opensearch-jvector` + IBM's `neural-search-jvector` fork). **A stock `opensearchproject/opensearch` image will not work** — index creation fails outright. This is not documented anywhere near the operator/Helm chart; you only discover it by reading `embedding_fields.py`. |
| **PostgreSQL** | OpenShift's built-in certified image stream (`image-registry.openshift-image-registry.svc:5000/openshift/postgresql:15-el9`) | The operator's `LangflowSpec` has no database field at all — Langflow defaults to SQLite (`LANGFLOW_DATABASE_URL: sqlite:////app/data/langflow.db`, see `internal/controller/env.go`). To use Postgres you deploy it yourself and override `spec.langflow.env` with `LANGFLOW_DATABASE_URL` (standard `postgresql://user:pass@host:port/db` — no async-driver suffix needed). This works but is completely undocumented; the direct Helm chart *does* have first-class Postgres support (`postgres.enabled`), so it's a real gap between the two installation paths. |
| **Docling (serve + worker)** | `spec.doclingComponents` on the CR, using `ghcr.io/docling-project/docling-serve-cpu:v1.15.1` for **both** serve and worker roles | See §3.7 below — the image name in the operator's own simple sample CR is wrong/nonexistent. |
| **Valkey (queue for Docling worker)** | Operator-managed via `spec.doclingComponents.valkey` | This part works well once you know it exists — one CR block, no manual manifests needed. |

## 3. Issues hit, in the order we hit them

### 3.1 — CRD too large for `kubectl/oc apply`
```
The CustomResourceDefinition "openrags.openr.ag" is invalid: metadata.annotations: Too long: must have at most 262144 bytes
```
`config/crd/bases/openr.ag_openrags.yaml` is large enough that `kubectl apply`'s computed `last-applied-configuration` annotation exceeds the Kubernetes 256KiB annotation limit. `oc create -f` works fine (no annotation computed). The operator's Helm chart works around this transparently via a `crds/` symlink into the same file and Helm's own install mechanics — but anyone installing the CRD manually via the documented `make install` (kustomize) or a raw `kubectl apply -f` hits this immediately.
**Fix applied:** `oc create -f config/crd/bases/openr.ag_openrags.yaml` instead of `apply`.
**Recommendation:** Note this explicitly in the operator README's "Option 2: kubectl + kustomize" section, or split/slim the CRD schema.

### 3.2 — Langflow container: `executable file 'langflow' not found in $PATH`
The operator hardcodes the Langflow container's command:
```go
// internal/controller/openrag_controller.go:999
Command: commandOrDefault(spec.Command, []string{"langflow"}),
Args:    argsOrDefault(spec.Args, []string{"run", "--env-file", "/app/.env"}),
```
This assumes the stock upstream Langflow image, which has a `langflow` CLI on `PATH`. This repo's own `openrag-langflow` image (`Dockerfile.langflow`) does **not** — its entrypoint is a custom wrapper script (`langflow-entrypoint`), and even its `CMD` is `python -m langflow run ...`, not a bare `langflow` invocation. The operator's default is simply wrong for the image it's meant to run.
**Fix applied:** Override in the CR:
```yaml
spec:
  langflow:
    command: ["python"]
    args: ["-m", "langflow", "run", "--host", "0.0.0.0", "--port", "7860", "--env-file", "/app/.env"]
```
**Recommendation:** Fix the operator's default to match the actual shipped image, or better, don't hardcode `Command`/`Args` at all — let the image's own `ENTRYPOINT`/`CMD` run unless the CR overrides them.

### 3.3 — Langflow entrypoint assumes it starts as root (breaks under any non-root-by-default runtime)
Having bypassed the operator's bad default and tried the image's own `ENTRYPOINT` (`langflow-entrypoint`) directly, it crashed:
```
File "/usr/local/bin/langflow-entrypoint", line 40, in <module>
    os.setuid(1000)
PermissionError: [Errno 1] Operation not permitted
```
`scripts/langflow-entrypoint.py` unconditionally does `chmod 0777` on a local bind-mount path, then `os.setuid(1000)` to drop from root to the `langflow` user — a workflow designed for the `Dockerfile.langflow` `USER root` → local macOS/Podman bind-mount permission fix. Under OpenShift's default `restricted-v2` SCC, the container **never starts as root in the first place** (an arbitrary non-root UID is assigned), so the process has no `CAP_SETUID` and the call fails outright. Every OpenShift cluster with default SCCs hits this.
**Fix applied:** Bypass the wrapper entirely and invoke `python -m langflow run ...` directly (same override as §3.2) — the wrapper's actual job (fixing a local bind-mount) doesn't apply on a PVC-backed volume anyway; PVC ownership is handled by the SCC-assigned `fsGroup`.
**Recommendation:** Make the wrapper conditional (`if os.getuid() == 0: drop_privileges()`), matching the "arbitrary UID" pattern already used correctly elsewhere in this repo (`Dockerfile.frontend`, `Dockerfile.backend`, and the root `Dockerfile` all handle this properly — Langflow's is the outlier).

### 3.4 — Langflow refuses to start with 4 workers and no shared job queue
```
RuntimeError: Refusing to start with 4 workers and the default in-memory job queue. POLLING and STREAMING event
delivery fail with 'Job not found' roughly half the time...
```
The operator's hardcoded default is `LANGFLOW_WORKERS=4` (`env.go`), which Langflow itself refuses without `LANGFLOW_JOB_QUEUE_TYPE=redis` configured.
**Fix applied:** `spec.langflow.env: [{name: LANGFLOW_WORKERS, value: "1"}]` — appropriate for this single-instance deployment.
**Recommendation:** Default to 1 worker (matches the direct Helm chart's own note: "Single pod - vertical scaling only"), or wire up Redis/Valkey automatically like `doclingComponents.valkey` already does for Docling.

### 3.5 — OpenSearch: `chown` to UID/GID 1000 instead of group 0 breaks arbitrary-UID execution
The custom `openrag-opensearch` image (repo-root `Dockerfile`) mostly follows the OpenShift "arbitrary UID, group 0" convention correctly — `chmod -R g=u /usr/share/opensearch` + `COPY --chown=$UID:0` for the bulk of the image. But the security config directory is handled separately, and incorrectly:
```dockerfile
COPY securityconfig/ /usr/share/opensearch/securityconfig/
RUN chown -R opensearch:opensearch /usr/share/opensearch/securityconfig/ /usr/share/opensearch/cloud_securityconfig/
```
This sets **GID 1000**, not GID 0. Under OpenShift, the container runs as an arbitrary UID whose *effective* group is 0 (no `/etc/passwd` entry for that UID → runtime falls back to GID 0) — so it has no write access to a UID/GID-1000-owned directory. The runtime's own `setup-security.sh` (generated inline in the same Dockerfile) tries to `sed` the freshly-generated admin password hash into `internal_users.yml` in that directory — the `sed -i` **silently fails** (no `set -e` anywhere in the script), and the container proceeds to push the **unmodified placeholder** into OpenSearch's live security index via `securityadmin.sh`:
```yaml
admin:
  reserved: true
  hash: "ADMIN_HASH_PLACEHOLDER"
```
Net effect: **no password authenticates as admin, ever**, on any OpenShift cluster, and the failure is completely silent — logs even say `"Security configuration applied successfully"`.
**Fix applied (required a cluster-admin action — flagged and confirmed with the user before doing it):** Ran this one pod under a dedicated ServiceAccount granted the `anyuid` SCC, with `runAsUser/runAsGroup: 1000` — i.e., forced it to run exactly as the UID that owns the files, matching how the image runs everywhere else (Compose, plain Docker).
**Recommendation:** This is the single highest-priority fix in this whole list. Either:
  - `chown --chown=$UID:0` the securityconfig directories like the rest of the image, and `chmod g=u` them, so arbitrary-UID execution works without any SCC exception, **or**
  - Add `set -e` to `setup-security.sh` so this fails loudly (container crash-loops with a clear error) instead of silently locking out all auth.
  Either change alone would have saved us hours of debugging; both together would be ideal.

### 3.6 — Wrong Postgres image name; RWO PVC's fine, no arbitrary-UID issue found
Initially tried `registry.access.redhat.com/ubi9/postgresql-16:latest` (guessed by analogy to other UBI images) — doesn't exist (`name unknown: Repo not found`). Switched to OpenShift's own built-in image stream (`image-registry.openshift-image-registry.svc:5000/openshift/postgresql:15-el9`), which is certified, already mirrored locally, and designed for arbitrary-UID execution out of the box — no further issues. Not a bug in this repo, just noting for anyone following the same path: **there is no ready-made Postgres reference for OpenShift in this repo at all**, unlike OpenSearch/Docling which at least have a working image name documented somewhere.

### 3.7 — Docling image names in the *simple* sample CR are placeholders that don't exist
`kubernetes/operator/config/samples/openrag_v1alpha1_openrag.yaml` (the primary, most-likely-to-be-copied sample) has:
```yaml
# doclingComponents:
#   serve:
#     image: langflowai/docling-serve:latest
#   worker:
#     image: langflowai/docling-worker:latest
```
Neither image exists on Docker Hub (`requested access to the resource is denied` — i.e., "doesn't exist or is private"). The **real**, working reference is only in the separate, much longer `config/samples/docling-complete.yaml`:
```yaml
serve:
  image: ghcr.io/docling-project/docling-serve-cpu:v1.15.1
worker:
  image: ghcr.io/docling-project/docling-serve-cpu:v1.15.1   # same image, different role
```
**Recommendation:** Fix the commented example in the primary sample CR to reference the real image — the current placeholder actively misleads anyone who copies it.

### 3.8 — docling-serve default resource sizing is too low for real use
With the CRD-sample-like defaults (2 CPU / 4Gi limits), `docling-serve` pegged at its CPU limit (1997m/2000m) and hovered near its memory limit converting even a single onboarding sample PDF, took 180+ seconds per file, and restarted once under the load.
**Fix applied:** Bumped to requests `2 CPU / 4Gi`, limits `4 CPU / 8Gi`.
**Recommendation:** Document that `docling-serve-cpu` needs meaningfully more headroom than the 500m/2Gi shown in the simple sample CR's comments — even the "complete" sample's 2/4Gi limits weren't quite enough. First-request latency in particular (model loading) should be called out.

### 3.9 — `docling-serve`/`docling-worker` Deployments use `RollingUpdate` despite RWO storage → permanent deadlock on any spec change
Every time we changed `spec.doclingComponents.serve`/`.worker` (image, resources), the rollout deadlocked:
```
Warning  FailedAttachVolume  Multi-Attach error for volume "pvc-..." Volume is already used by pod(s) docling-serve-<old-hash>
```
The old ReplicaSet's pod holds the (ReadWriteOnce) PVC and is never scaled down, because the new ReplicaSet's pod can never become `Ready` without mounting that same volume — a textbook `RollingUpdate` + single-replica-RWO-volume deadlock. Frontend/backend/langflow deployments in this same operator correctly use `Strategy: Recreate` for exactly this reason; the Docling components do not.
**Fix applied (twice, for both the initial deploy and the resource bump):** Manually `oc scale rs <stale-rs> --replicas=0` to break the deadlock, then `oc patch deployment docling-serve/docling-worker --type=merge -p '{"spec":{"strategy":{"type":"Recreate", ...}}}'` to prevent recurrence.
**Recommendation:** Set `Strategy: Recreate` for the docling-serve and docling-worker Deployments in the controller code, matching the pattern already used for frontend/backend/langflow.

### 3.10 — Onboarding wizard's sample-data ingestion always fails (401) — surfaces a much bigger, silent problem
The onboarding wizard's `INGEST_SAMPLE_DATA=true` default tries to auto-ingest 3 demo documents as part of `POST /onboarding`. This consistently failed:
```
opensearchpy.exceptions.AuthenticationException: AuthenticationException(401, 'Unauthorized')
```
with the OpenSearch-side log showing:
```
No JWK are available from IdP
No 'Authorization' header, send 401 and 'WWW-Authenticate Basic'
```
Chasing this down surfaced the actual root cause, which is **not specific to sample-data ingestion or anonymous users — it breaks every per-user OpenSearch call, for every real logged-in user too** (confirmed once we got a real user session into the Knowledge page: `search`, `files`, `check-filename` all 401'd the same way).

**Root cause:** This deployment's OpenSearch security config authenticates non-admin traffic via OIDC/JWT, fetching its JWKS from the backend (`.../.well-known/openid-configuration` → `.../auth/jwks`, both served correctly and reachable). But:
```go
// src/session_manager.py — _configure_jwt_signing()
if signing_key.lstrip().startswith("-----BEGIN"):
    # RSA/EC/Ed25519 → sets self.public_key_pem, algorithm RS256/ES*/EdDSA
else:
    # Plain string = symmetric (HS256)
    self.public_key_pem = None   # No JWKS for symmetric
    self.algorithm = "HS256"
```
The **operator's own auto-generated `JWT_SIGNING_KEY`** (when `spec.backend.jwtSigningKeySecret` is omitted, which every sample CR in the repo does) is a **plain random string**, not a PEM-encoded key. The backend correctly falls back to symmetric HS256 signing — this is working as designed on the backend side — but that means `public_key_pem` is permanently `None`, `/auth/jwks` permanently returns `{"keys": []}`, and OpenSearch's RS256-JWT-based authenticator can **never validate a single JWT, for any user, under any circumstances**, with the operator's own default configuration.

This is a fully out-of-the-box, day-one breakage for anyone deploying via the operator with its documented defaults, against an OpenSearch instance running this repo's own custom security config (i.e., the `langflowai/openrag-opensearch` image everyone is pointed at, per §3.5). Basic-auth/admin operations (cluster health, index creation) work fine, which is why this doesn't show up immediately — only per-user request paths break, and only once you get far enough to actually use the app.

**Fix applied:**
1. Skipped sample-data ingestion (`INGEST_SAMPLE_DATA=false`) to unblock onboarding completion — this only masks the symptom for that one flow, not the underlying issue.
2. Generated a real 2048-bit RSA keypair, stored it as a Kubernetes Secret, and set `spec.backend.jwtSigningKeySecret` to reference it — this actually fixes JWT verification for all users.

**A further wrinkle:** the operator has a (well-intentioned) safety guard preventing exactly this kind of after-the-fact change:
```go
// getOrGenerateSecret()
if userProvidedValue != "" && existingValue != "" {
    if userProvidedValue != existingValue {
        return "", fmt.Errorf("security violation: %s value mismatch ...")
    }
}
```
Since an auto-generated default secret already existed (from the very first reconcile), providing a real key put the CR into a permanent `Error` phase: `"security violation: JWT_SIGNING_KEY value mismatch ... this is not allowed for critical security keys"`. There is no CR field or documented procedure to intentionally rotate this. We had to manually delete both the operator's auto-generated default secret (`<name>-jwt-signing-key-default`) *and* the rendered `<name>-be-env` secret — both of which carry `openr.ag/user-secret-protection` / `openr.ag/env-secret-protection` finalizers that are **only removed by the operator's CR-deletion reconcile path**, which never runs during a normal (non-deleting) reconcile — so even the delete itself hung until we manually stripped the finalizers (`oc patch secret ... -p '{"metadata":{"finalizers":[]}}'`).

**Recommendations (highest priority after §3.5):**
- Make the operator's auto-generated `JWT_SIGNING_KEY` default an **RSA key**, not a random string, so JWT verification works out of the box against this repo's own reference OpenSearch security config. (If HS256 is intentionally the supported default elsewhere, e.g. SaaS, then the OpenShift/self-hosted docs need to say explicitly "you must provide your own RSA `jwtSigningKeySecret`, or per-user OpenSearch access will silently 401 for everyone.")
- At minimum, document this interaction prominently — it's a genuinely hard failure mode to diagnose from symptoms alone (a 401 on document search looks like a credentials problem, not a signing-algorithm mismatch four layers removed).
- Provide a supported key-rotation path (a CR field, an annotation, or a documented `oc delete secret <default> <env>` + finalizer-strip procedure) instead of leaving the safety guard as a dead end.

## 4. Cluster environment specifics (IBM TechZone / OpenShift 4.18)

- **Storage:** `ocs-storagecluster-ceph-rbd` (default StorageClass, Ceph RBD, RWO) used for every PVC — Postgres, OpenSearch, backend, Langflow, Docling serve/worker, Valkey. The operator's per-component `PersistenceSpec` only ever creates single, independent PVCs (unlike the direct Helm chart's separate RWX "shared" volume model) — **RWX storage was never needed** for the operator path. `ocs-storagecluster-cephfs` (RWX) is available on this cluster but unused.
- **`vm.max_map_count`:** already `262144` cluster-wide on all worker nodes — no MachineConfig change needed for OpenSearch's bootstrap check. Worth confirming this isn't assumed/undocumented, since a cluster without cluster-level tuning would need a privileged Machine Config change (node reboot) that's well outside "just install the app" scope.
- **Ingress:** used an OpenShift `Route` (edge TLS) for the frontend; the CR has no Route/Ingress support at all, so this is 100% manual regardless of cluster.
- **RBAC/SCC exceptions granted (see full detail in §3.5, §3.9's related item):**
  - `anyuid` SCC → dedicated `openrag-opensearch` ServiceAccount (scoped to one workload only).
  - Patched the operator's own `ClusterRole` (Helm-installed) to add `apps/statefulsets` and `autoscaling/horizontalpodautoscalers` — **missing from the Helm chart's RBAC template but present in the kustomize source** (`config/rbac/role.yaml`). Without this, the operator can reconcile everything except the Valkey `StatefulSet`, which silently never gets created (the reflector just logs `Failed to watch ... forbidden` in a loop; nothing in CR status flags it). **This is a straightforward chart-drift bug** — the Helm and kustomize RBAC sources should be generated from the same place or kept in lockstep by CI.

## 5. Summary — priority-ordered recommendations

1. **Fix the JWT signing key default (§3.10).** Highest-impact, silent, breaks all real usage out of the box.
2. **Fix OpenSearch image's securityconfig ownership + add `set -e` to `setup-security.sh` (§3.5).** Second-highest — total, silent auth lockout under arbitrary-UID execution (i.e., every OpenShift/PSA-restricted cluster).
3. **Fix the Langflow container command defaults + entrypoint's root assumption (§3.2, §3.3).** Blocks the operator path entirely on any non-privileged runtime.
4. **Sync the Helm chart's operator RBAC with the kustomize source (§4).** Easy, mechanical fix; currently silently breaks Docling/Valkey and any future HPA usage.
5. **Fix Docling Deployment strategy to `Recreate` (§3.9).** Easy fix, currently guarantees a deadlock on the very first config change anyone makes.
6. **Fix the placeholder Docling image names in the primary sample CR (§3.7).** Low effort, actively misleads.
7. **Default `LANGFLOW_WORKERS=1` (§3.4) and raise Docling resource defaults (§3.8).**
8. **Add an OpenShift/self-hosted "getting started" doc** covering: the `jvector`-only OpenSearch image requirement, the fact that Postgres/OpenSearch/Docling are BYO, and the JWT signing key requirement — ideally with a tested reference set of manifests (even just what's in this document) so the next deployer isn't rediscovering all of the above from scratch.

---
*Compiled from a live deployment session against an OpenShift 4.18.48 cluster (IBM TechZone, OpenShift Data Foundation storage), operator chart v0.1.0 / app v0.1.52, `main` branch of `langflow-ai/openrag` as of 2026-09-22/23.*
