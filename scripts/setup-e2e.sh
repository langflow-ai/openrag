#!/bin/bash
set -e

# Go to project root
cd "$(dirname "$0")/.."

# Environment file for E2E tests
E2E_ENV="frontend/.env.test"
E2E_ENV_EXAMPLE="frontend/.env.test.example"

# Create .env.test from the example template (never modify the tracked example file)
if [ ! -f "$E2E_ENV" ]; then
    cp "$E2E_ENV_EXAMPLE" "$E2E_ENV"
fi

# Auto-generate a strong OpenSearch password if not already set in the env file.
# OpenSearch requires: uppercase, lowercase, digit, special char, min 8 chars.
CURRENT_PASSWORD=$(grep -E '^OPENSEARCH_PASSWORD=' "$E2E_ENV" | cut -d'=' -f2-)
if [ -z "$CURRENT_PASSWORD" ]; then
    # Generate a random base (alphanumeric) and append required character classes
    RANDOM_BASE=$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 12)
    GENERATED_PASSWORD="${RANDOM_BASE}Aa1@"
    echo "Auto-generated OpenSearch password for E2E tests."

    # Write the password into the env file
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|^OPENSEARCH_PASSWORD=.*|OPENSEARCH_PASSWORD=${GENERATED_PASSWORD}|" "$E2E_ENV"
    else
        sed -i "s|^OPENSEARCH_PASSWORD=.*|OPENSEARCH_PASSWORD=${GENERATED_PASSWORD}|" "$E2E_ENV"
    fi

    export OPENSEARCH_PASSWORD="$GENERATED_PASSWORD"
else
    echo "Using existing OpenSearch password from $E2E_ENV."
    export OPENSEARCH_PASSWORD="$CURRENT_PASSWORD"
fi

# Detect container runtime
if command -v docker >/dev/null 2>&1; then
    CONTAINER_RUNTIME="docker"
else
    CONTAINER_RUNTIME="podman"
fi

echo "Using container runtime: $CONTAINER_RUNTIME"
echo "Starting E2E Setup using $E2E_ENV..."

# Clean up using make
echo "Cleaning up..."
make factory-reset FORCE=true ENV_FILE=$E2E_ENV

# Start infrastructure using make (this will use the new .env)
echo "Starting infrastructure..."
make dev-local-cpu ENV_FILE=$E2E_ENV

echo "Waiting for OpenSearch..."
TIMEOUT=300
ELAPSED=0
until curl -s -k https://localhost:9200 >/dev/null; do
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    if [ $ELAPSED -ge $TIMEOUT ]; then
        echo "ERROR: OpenSearch did not become ready within ${TIMEOUT}s"
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

echo "Infrastructure Ready!"
