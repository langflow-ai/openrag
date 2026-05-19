# OpenRAG Operator

A Kubernetes operator that manages OpenRAG deployments via a single `OpenRAG` custom resource.
It creates and owns the frontend, backend, and Langflow deployments, services, and service accounts.
External dependencies (OpenSearch, Docling) are referenced by connection config — not deployed by this operator.

## Prerequisites

- Go 1.26.0 (`gvm use go1.26.0`)
- kubectl pointed at a cluster
- Helm 3.x (for Helm chart installation)

## Installation

### Option 1: Using Helm (Recommended)

The Helm chart deploys both the CRDs and the operator deployment.

```bash
# Install from local chart
helm install openrag-operator ./kubernetes/helm/operator \
  --namespace openrag-control \
  --create-namespace

# Verify installation
kubectl get deployment -n openrag-control
kubectl get crd openrags.openr.ag
```

**Customize installation:**

```bash
# Set custom image tag
helm install openrag-operator ./kubernetes/helm/operator \
  --namespace openrag-control \
  --create-namespace \
  --set image.tag=v0.1.0

# Or use a values file
helm install openrag-operator ./kubernetes/helm/operator \
  --namespace openrag-control \
  --create-namespace \
  -f my-values.yaml
```

### Option 2: Using kubectl + kustomize

```bash
# Install CRDs
make install

# Deploy the operator
make deploy IMG=ghcr.io/langflow-ai/openrag-operator:latest
```

### Option 3: Local development (see below)

## Local development cluster (kind + podman)

### 1. Start the podman machine

```bash
podman machine start
```

### 2. Configure kind to use podman

```bash
export KIND_EXPERIMENTAL_PROVIDER=podman
```

Add this to your shell profile (`~/.zshrc` or `~/.bashrc`) to make it permanent.

### 3. Create the cluster

```bash
kind create cluster --name openrag
```

Verify it is running:

```bash
kubectl cluster-info --context kind-openrag
kubectl get nodes
```

### 3a. Start the podman machine if it's not running after restart your laptop
```bash
podman start openrag-control-plane
kubectl config use-context kind-openrag  
```

### 4. Load a locally built operator image (optional)

If you built the image locally instead of pulling from GHCR:

```bash
make docker-build IMG=openrag-operator:dev
podman save openrag-operator:dev | kind load image-archive /dev/stdin --name openrag
```

Install CRD

```bash
make install
```

Run the operator locally:

```bash
make run
```

Apply a sample CR (create the namespace first; the operator does not create it when `metadata.namespace` equals `targetNamespace`):

```bash
kubectl create namespace my-tenant
# kind/Colima clusters usually have only 2 CPUs — use the kind-local sample:
kubectl apply -f config/samples/openrag_v1alpha1_openrag-kind-local.yaml
kubectl get pods -n my-tenant
```

On a 2-CPU kind node, the default sample (`openrag_v1alpha1_openrag.yaml`) requests 1500m CPU for frontend+backend+langflow and langflow will stay `Pending` with `Insufficient cpu`.

### Build app images locally and use them in kind (Colima/Docker)

From the **repository root** (not `kubernetes/operator/`):

```bash
# Build backend, frontend, langflow and load into the kind node
make kind-build-load-apps

# In another terminal: operator + CR (kind-local sets imagePullPolicy: Never)
cd kubernetes/operator
make install
make run

kubectl create namespace my-tenant
kubectl apply -f config/samples/openrag_v1alpha1_openrag-kind-local.yaml
```

Images are tagged the same as upstream (`langflowai/openrag-*:latest`) so the kind-local sample does not need custom names. `imagePullPolicy: Never` forces the cluster to use the copies loaded with `kind load docker-image`.

After you change code and rebuild:

```bash
make kind-build-load-apps   # or build only what changed, then make kind-load-app-images
kubectl rollout restart deployment -n my-tenant openrag-fe openrag-be openrag-lf
```

Optional: build/load the **operator** image the same way:

```bash
cd kubernetes/operator
make docker-build IMG=openrag-operator:dev
kind load docker-image openrag-operator:dev --name openrag
make deploy IMG=openrag-operator:dev   # instead of make run
```

### 5. Tear down

```bash
kind delete cluster --name openrag
```

## Quick start (development)

```bash
make deps          # download controller-gen, kustomize, envtest into ./bin
make manifests     # regenerate CRD + RBAC YAML (run after editing types)
make generate      # regenerate DeepCopy methods (run after editing types)
make build         # compile bin/manager
make install       # install the CRD into the current cluster
make deploy IMG=ghcr.io/langflow-ai/openrag-operator:latest
```

Apply the sample CR:

```bash
kubectl apply -f config/samples/openrag_v1alpha1_openrag.yaml
kubectl get openrag
```

## Helm Chart

The operator Helm chart is located at `kubernetes/helm/operator/` with the following structure:

```
kubernetes/helm/operator/
├── Chart.yaml                     # Chart metadata
├── values.yaml                    # Default configuration values
├── .helmignore                    # Files to ignore when packaging
├── crds/
│   └── openr.ag_openrags.yaml    # OpenRAG CRD (auto-installed)
└── templates/
    ├── _helpers.tpl               # Template helpers
    ├── NOTES.txt                  # Post-install notes
    ├── deployment.yaml            # Operator deployment
    ├── serviceaccount.yaml        # Service account
    ├── role.yaml                  # ClusterRole for operator
    ├── rolebinding.yaml           # ClusterRoleBinding
    ├── leader_election_role.yaml  # Role for leader election
    └── leader_election_rolebinding.yaml
```

### Helm Chart Configuration

Key configurable values in `values.yaml`:

```yaml
image:
  repository: ghcr.io/langflow-ai/openrag-operator
  tag: ""  # defaults to chart appVersion
  pullPolicy: IfNotPresent

replicaCount: 1

resources:
  limits:
    cpu: 500m
    memory: 128Mi
  requests:
    cpu: 10m
    memory: 64Mi

leaderElection:
  enabled: true

nodeSelector: {}
tolerations: []
affinity: {}
```

### Helm Chart Operations

**Lint the chart:**
```bash
helm lint ./kubernetes/helm/operator
```

**Template the chart (dry-run):**
```bash
helm template openrag-operator ./kubernetes/helm/operator \
  --namespace openrag-control
```

**Package the chart:**
```bash
helm package ./kubernetes/helm/operator
```

**Upgrade the operator:**
```bash
helm upgrade openrag-operator ./kubernetes/helm/operator \
  --namespace openrag-control
```

**Uninstall:**
```bash
helm uninstall openrag-operator --namespace openrag-control
```

**Note:** CRDs are not automatically upgraded by Helm. If the CRD changes, manually apply it:
```bash
kubectl apply -f kubernetes/helm/operator/crds/openr.ag_openrags.yaml
```

## CR overview

```yaml
apiVersion: openr.ag/v1alpha1
kind: OpenRAG
metadata:
  name: my-openrag
spec:
  frontend:
    image: langflowai/openrag-frontend:latest
  backend:
    image: langflowai/openrag-backend:latest
    envSecret: my-backend-env      # Secret with a ".env" key
    storage:
      enabled: true
      size: 10Gi
  langflow:
    image: langflowai/openrag-langflow:latest
    envSecret: my-langflow-env
    storage:
      enabled: true
      size: 10Gi
  opensearch:
    host: opensearch-coordinating.opensearch.svc.cluster.local
    credentialsSecret: opensearch-credentials   # keys: username, password
  # docling:                        # optional
  #   host: docling-serve.docling.svc.cluster.local
  networkPolicy:
    enabled: false
```

See [`config/samples/openrag_v1alpha1_openrag.yaml`](config/samples/openrag_v1alpha1_openrag.yaml) for a full annotated example.

## Release Process

The operator uses GitHub Actions for automated releases:

### Docker Image Publishing

Images are automatically published to GitHub Container Registry (GHCR) when you push a tag:

```bash
# Create and push a release tag
git tag operator/v0.1.0
git push origin operator/v0.1.0
```

This triggers the `.github/workflows/operator-release.yml` workflow which:
1. Builds multi-architecture images (linux/amd64, linux/arm64)
2. Pushes to `ghcr.io/<owner>/openrag-operator:v0.1.0`
3. Creates a multi-arch manifest with `:latest` tag
4. Creates a GitHub release with release notes

**Manual trigger:**
You can also trigger the release workflow manually from the GitHub Actions UI with a custom tag.

**Image location:**
- Registry: `ghcr.io`
- Repository: `ghcr.io/langflow-ai/openrag-operator`
- Tags: `v0.1.0`, `v0.1.0-amd64`, `v0.1.0-arm64`, `latest`

### Helm Chart Publishing

(To be implemented) Helm charts can be published to GitHub Pages or a Helm repository using GitHub Actions.
