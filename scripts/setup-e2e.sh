#!/bin/bash
set -e

# Go to project root
cd "$(dirname "$0")/.."

# Detect container runtime
if command -v docker >/dev/null 2>&1; then
    CONTAINER_RUNTIME="docker"
else
    CONTAINER_RUNTIME="podman"
fi

echo "Using container runtime: $CONTAINER_RUNTIME"
echo "Starting E2E Setup..."

# Pre-create langflow-data as world-writable so the Langflow container (UID 1000)
# and the runner (UID 1001) can both access it, regardless of Docker's :U flag behavior.
mkdir -p langflow-data
chmod 777 langflow-data

# Start full stack using make
echo "Starting full stack (CPU)..."
make dev-cpu

echo "Starting docling..."
make docling

# Forward backend port 8000 using a proxy container
# We find the network of the backend container and use a proxy to bridge it to the host.
echo "Starting backend port forwarder at localhost:8000..."
${CONTAINER_RUNTIME} rm -f openrag-backend-proxy 2>/dev/null || true
BACKEND_NETWORK=$(${CONTAINER_RUNTIME} inspect openrag-backend -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' | head -n 1)
${CONTAINER_RUNTIME} run -d --rm \
    --name openrag-backend-proxy \
    --network "$BACKEND_NETWORK" \
    -p 8000:8000 \
    alpine/socat TCP-LISTEN:8000,fork,reuseaddr TCP:openrag-backend:8000

# On Linux/CI, Docker volumes are root-owned. Fix them so the host runner can write to them.
if [ "$CI" = "true" ] && [[ "$OSTYPE" != "darwin"* ]]; then
    echo "Fixing volume permissions for CI..."
    ${CONTAINER_RUNTIME} run --rm -v "$(pwd):/work" alpine sh -c "chown -R $(id -u):$(id -g) /work/config /work/data /work/keys /work/opensearch-data /work/openrag-documents || true"
    chmod -R 777 config data keys opensearch-data openrag-documents 2>/dev/null || true
fi

echo "Waiting for OpenSearch..."
TIMEOUT=300
ELAPSED=0
until curl -s -k https://localhost:9200 >/dev/null; do
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    if [ $ELAPSED -ge $TIMEOUT ]; then
        echo "ERROR: OpenSearch did not become ready within ${TIMEOUT}s"
        ${CONTAINER_RUNTIME:-docker} logs os 2>&1 | tail -n 100
        exit 1
    fi
    echo "Waiting for OpenSearch... (${ELAPSED}s/${TIMEOUT}s)"
done

echo "Waiting for Langflow..."
ELAPSED=0
until curl -s http://localhost:7860/health >/dev/null; do
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    if [ $ELAPSED -ge $TIMEOUT ]; then
        echo "ERROR: Langflow did not become ready within ${TIMEOUT}s"
        exit 1
    fi
    echo "Waiting for Langflow... (${ELAPSED}s/${TIMEOUT}s)"
done

echo "Waiting for Frontend..."
ELAPSED=0
until curl -s http://localhost:3000 >/dev/null; do
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    if [ $ELAPSED -ge $TIMEOUT ]; then
        echo "ERROR: Frontend did not become ready within ${TIMEOUT}s"
        exit 1
    fi
    echo "Waiting for Frontend... (${ELAPSED}s/${TIMEOUT}s)"
done

echo "Waiting for Backend (via proxy)..."
ELAPSED=0
until curl -s http://localhost:8000/health >/dev/null; do
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    if [ $ELAPSED -ge $TIMEOUT ]; then
        echo "ERROR: Backend did not become ready within ${TIMEOUT}s"
        ${CONTAINER_RUNTIME} logs openrag-backend 2>&1 | tail -n 100
        exit 1
    fi
    echo "Waiting for Backend... (${ELAPSED}s/${TIMEOUT}s)"
done

echo "Infrastructure Ready!"
