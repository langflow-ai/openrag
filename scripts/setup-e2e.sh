#!/bin/bash
set -e

# Parse command line arguments
SKIP_CERT_VALIDATION=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-cert-validation|--insecure)
            SKIP_CERT_VALIDATION=true
            echo "WARNING: Certificate validation disabled via command line flag"
            echo "WARNING: This should only be used in trusted development environments"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-cert-validation  Skip SSL certificate validation (INSECURE)"
            echo "                          Only use in trusted development environments"
            echo "  -h, --help             Show this help message"
            echo ""
            echo "Environment Variables:"
            echo "  OPENSEARCH_CA_CERT     Path to OpenSearch CA certificate"
            echo "                         (default: securityconfig/root-ca.pem)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Run '$0 --help' for usage information"
            exit 1
            ;;
    esac
done

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

# Extract CA certificate from OpenSearch container for secure HTTPS communication
echo "Extracting OpenSearch CA certificate..."
CERT_EXTRACT_TIMEOUT=60
CERT_EXTRACT_ELAPSED=0

# Wait for OpenSearch container to be running and certificate to be available
until ${CONTAINER_RUNTIME} exec os test -f /usr/share/opensearch/config/root-ca.pem 2>/dev/null; do
    sleep 2
    CERT_EXTRACT_ELAPSED=$((CERT_EXTRACT_ELAPSED + 2))
    if [ $CERT_EXTRACT_ELAPSED -ge $CERT_EXTRACT_TIMEOUT ]; then
        echo "WARNING: Could not extract CA certificate from OpenSearch container within ${CERT_EXTRACT_TIMEOUT}s"
        echo "WARNING: Certificate validation will be skipped"
        SKIP_CERT_VALIDATION=true
        break
    fi
    echo "Waiting for OpenSearch certificate... (${CERT_EXTRACT_ELAPSED}s/${CERT_EXTRACT_TIMEOUT}s)"
done

# Extract the certificate if available
if [ "$SKIP_CERT_VALIDATION" != "true" ]; then
    mkdir -p securityconfig
    if ${CONTAINER_RUNTIME} cp os:/usr/share/opensearch/config/root-ca.pem securityconfig/root-ca.pem 2>/dev/null; then
        echo "Successfully extracted CA certificate to securityconfig/root-ca.pem"
        chmod 644 securityconfig/root-ca.pem
    else
        echo "WARNING: Failed to extract CA certificate from container"
        echo "WARNING: Certificate validation will be skipped"
        SKIP_CERT_VALIDATION=true
    fi
fi

echo "Waiting for OpenSearch..."
TIMEOUT=300
ELAPSED=0

# Determine curl options based on validation mode
if [ "$SKIP_CERT_VALIDATION" = "true" ]; then
    echo "WARNING: Skipping certificate validation (insecure mode)"
    CURL_OPTS="-k"
else
    # Strict mode: Require proper certificate setup
    OPENSEARCH_CA_CERT="${OPENSEARCH_CA_CERT:-securityconfig/root-ca.pem}"
    
    if [ ! -f "$OPENSEARCH_CA_CERT" ]; then
        echo "ERROR: OpenSearch CA certificate not found at: $OPENSEARCH_CA_CERT"
        echo "ERROR: Certificate validation is required for secure operation"
        echo ""
        echo "To fix this issue, you must:"
        echo "  1. Extract the CA certificate from OpenSearch container, OR"
        echo "  2. Provide a valid CA certificate at: $OPENSEARCH_CA_CERT, OR"
        echo "  3. Set OPENSEARCH_CA_CERT environment variable to the cert path"
        echo ""
        echo "For development/testing ONLY, you can bypass validation with:"
        echo "  $0 --skip-cert-validation"
        echo ""
        exit 1
    fi
    
    echo "Using certificate validation with CA cert: $OPENSEARCH_CA_CERT"
    CURL_OPTS="--cacert"
    CURL_CERT_PATH="$OPENSEARCH_CA_CERT"
fi

until curl -s $CURL_OPTS ${CURL_CERT_PATH:+"$CURL_CERT_PATH"} https://localhost:9200 >/dev/null; do
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
until [ "$(curl -s http://localhost:8000/search/health -o /dev/null -w "%{http_code}")" -eq 200 ]; do
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    if [ $ELAPSED -ge $TIMEOUT ]; then
        echo "ERROR: Backend did not become ready within ${TIMEOUT}s"
        ${CONTAINER_RUNTIME} logs openrag-backend 2>&1 | tail -n 100
        exit 1
    fi
    echo "Waiting for Backend... (${ELAPSED}s/${TIMEOUT}s)"
done

echo "Waiting for OpenSearch security configuration to be applied..."
ELAPSED=0
until ${CONTAINER_RUNTIME} logs os 2>&1 | grep -q "Security configuration applied successfully" || [ $ELAPSED -ge 60 ]; do
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done
if [ $ELAPSED -ge 60 ]; then
    echo "WARNING: OpenSearch security configuration wait timed out (60s)"
else
    echo "OpenSearch security configuration applied successfully"
fi

echo "Infrastructure Ready!"
