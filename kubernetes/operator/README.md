# OpenRAG Operator

A Kubernetes operator that manages OpenRAG deployments via a single `OpenRAG` custom resource.
It creates and owns the frontend, backend, and Langflow deployments, services, and service accounts.
External dependencies (OpenSearch, Docling) are referenced by connection config — not deployed by this operator.

## Prerequisites

- Go 1.26.0 (`gvm use go1.26.0`)
- kubectl pointed at a cluster

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
go run cmd/main.go
```

### 5. Tear down

```bash
kind delete cluster --name openrag
```

## Quick start

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
