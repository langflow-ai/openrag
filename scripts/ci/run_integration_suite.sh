#!/usr/bin/env bash
set -euo pipefail

suite="${1:-${TEST_SUITE:-core}}"
container_runtime="${CONTAINER_RUNTIME:-$(command -v docker >/dev/null 2>&1 && echo docker || echo podman)}"
env_file="${ENV_FILE:-.env}"

if [[ -f "$env_file" ]]; then
  compose_cmd=("$container_runtime" compose --env-file "$env_file")
else
  compose_cmd=("$container_runtime" compose)
fi

red=$'\033[0;31m'
purple=$'\033[38;2;119;62;255m'
yellow=$'\033[1;33m'
cyan=$'\033[0;36m'
green=$'\033[0;32m'
nc=$'\033[0m'

test_result=0

wait_for_url() {
  local label="$1"
  local url="$2"
  local attempts="${3:-60}"

  echo "${yellow}Waiting for ${label}...${nc}"
  for _ in $(seq 1 "$attempts"); do
    if curl -s "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  echo "${red}Timed out waiting for ${label} at ${url}${nc}"
  return 1
}

test_jwt_opensearch() {
  echo "${cyan}=== JWT OpenSearch Authentication Test ===${nc}"
  echo "${yellow}Generating test JWT token...${nc}"
  test_token="$(uv run python -c 'from utils.logging_config import configure_logging; configure_logging(log_level="CRITICAL"); from src.session_manager import SessionManager, AnonymousUser; sm = SessionManager("test"); print(sm.create_jwt_token(AnonymousUser()).removeprefix("Bearer "))' 2>/dev/null)"
  if [[ -z "$test_token" ]]; then
    echo "${red}Failed to generate JWT token${nc}"
    return 1
  fi

  echo "${yellow}Testing JWT against OpenSearch...${nc}"
  response_file="$(mktemp /tmp/jwt-os-diag.XXXXXX)"
  if ! curl --fail-with-body -k -s \
    -o "$response_file" \
    -H "Authorization: Bearer $test_token" \
    -H "Content-Type: application/json" \
    https://localhost:9200/documents/_search \
    -d '{"query":{"match_all":{}}}'; then
    echo "${red}curl command failed (network error or HTTP 4xx/5xx)${nc}"
    head -c 400 "$response_file" 2>/dev/null || true
    rm -f "$response_file"
    return 1
  fi

  echo "${green}Success - OpenSearch accepted JWT${nc}"
  echo "Response preview:"
  head -c 200 "$response_file" | sed 's/^/  /' || true
  rm -f "$response_file"
  echo ""
}

dump_logs() {
  echo "${red}=== Tests failed, dumping container logs ===${nc}"
  echo ""
  echo "${yellow}=== Langflow logs (last 500 lines) ===${nc}"
  "$container_runtime" logs langflow 2>&1 | tail -500 || echo "${red}Could not get Langflow logs${nc}"
  echo ""
  echo "${yellow}=== Backend logs (last 500 lines) ===${nc}"
  "$container_runtime" logs openrag-backend 2>&1 | tail -500 || echo "${red}Could not get backend logs${nc}"
  echo ""
  echo "${yellow}=== Frontend logs (last 300 lines) ===${nc}"
  "$container_runtime" logs openrag-frontend 2>&1 | tail -300 || echo "${red}Could not get frontend logs${nc}"
  echo ""
  echo "${yellow}=== OpenSearch logs (last 300 lines) ===${nc}"
  "$container_runtime" logs os 2>&1 | tail -300 || echo "${red}Could not get OpenSearch logs${nc}"
  echo ""
}

teardown() {
  local status=$?
  if [[ "$status" -ne 0 && "$test_result" -eq 0 ]]; then
    test_result="$status"
  fi

  if [[ "$test_result" -ne 0 ]]; then
    dump_logs || true
  fi

  echo "${yellow}Tearing down infra${nc}"
  uv run python scripts/docling_ctl.py stop || true
  "${compose_cmd[@]}" down -v 2>/dev/null || true

  exit "$test_result"
}
trap teardown EXIT

if [[ -z "${OPENSEARCH_PASSWORD:-}" ]]; then
  echo "${red}OPENSEARCH_PASSWORD is required${nc}"
  exit 1
fi

echo "${yellow}Installing test dependencies...${nc}"
uv sync --group dev

echo "::group::Start Infrastructure"
echo "${yellow}Cleaning up old containers and volumes...${nc}"
"${compose_cmd[@]}" down -v 2>/dev/null || true

echo "${yellow}Starting infra for suite '${suite}' with OpenRAG version '${OPENRAG_VERSION:-latest}'${nc}"
OPENSEARCH_HOST=opensearch "${compose_cmd[@]}" up -d opensearch dashboards langflow openrag-backend openrag-frontend

echo "${cyan}Architecture: $(uname -m), Platform: $(uname -s)${nc}"
echo "${yellow}Starting docling-serve...${nc}"
docling_start_failed=0
docling_start_output="$(uv run python scripts/docling_ctl.py start --port 5001 --timeout 180 2>&1)" || docling_start_failed=1
echo "$docling_start_output"
if [[ "$docling_start_failed" = "1" ]]; then
  echo "${red}ERROR: docling_ctl.py start failed. Output above.${nc}"
  uv run python scripts/docling_ctl.py status 2>&1 || true
  exit 1
fi

docling_endpoint="$(echo "$docling_start_output" | grep "Endpoint:" | awk '{print $2}')"
if [[ -z "$docling_endpoint" ]]; then
  echo "${red}WARNING: docling-serve did not report an endpoint. Defaulting to http://localhost:5001${nc}"
  docling_endpoint="http://localhost:5001"
fi

echo "${purple}Docling-serve started at ${docling_endpoint}${nc}"
echo "${yellow}Docling-serve status check:${nc}"
uv run python scripts/docling_ctl.py status 2>&1 || true

echo "${yellow}Waiting for backend OIDC endpoint...${nc}"
for i in $(seq 1 60); do
  if "$container_runtime" exec openrag-backend curl -s http://localhost:8000/.well-known/openid-configuration >/dev/null 2>&1; then
    break
  fi
  if [[ "$i" -eq 60 ]]; then
    echo "${red}Backend OIDC endpoint was not reachable in time${nc}"
    exit 1
  fi
  sleep 2
done

echo "${yellow}Fixing JWT key ownership for test runner (host UID $(id -u))...${nc}"
"$container_runtime" run --rm -v "$(pwd)/keys:/keys" alpine sh -c "chown $(id -u):$(id -g) /keys/private_key.pem /keys/public_key.pem 2>/dev/null; chmod 600 /keys/private_key.pem; chmod 644 /keys/public_key.pem 2>/dev/null" 2>/dev/null || true

echo "${yellow}Waiting for OpenSearch security config to be fully applied...${nc}"
for i in $(seq 1 60); do
  if "$container_runtime" logs os 2>&1 | grep -q "Security configuration applied successfully"; then
    echo "${purple}Security configuration applied${nc}"
    break
  fi
  if [[ "$i" -eq 60 ]]; then
    echo "${red}OpenSearch security config was not applied in time${nc}"
    exit 1
  fi
  sleep 2
done

echo "${yellow}Verifying OIDC authenticator is active in OpenSearch...${nc}"
for i in $(seq 1 30); do
  authc_config="$(curl -k -s -u "admin:${OPENSEARCH_PASSWORD}" https://localhost:9200/_opendistro/_security/api/securityconfig 2>/dev/null || true)"
  if echo "$authc_config" | grep -q "openid_auth_domain"; then
    echo "${purple}OIDC authenticator configured${nc}"
    echo "$authc_config" | grep -A 5 "openid_auth_domain" || true
    break
  fi
  if [[ "$i" -eq 30 ]]; then
    echo "${red}OIDC authenticator NOT found or unreachable in time!${nc}"
    echo "Security config output: $authc_config"
    exit 1
  fi
  sleep 2
done

wait_for_url "Langflow" "http://localhost:7860/" 60
wait_for_url "docling-serve at ${docling_endpoint}" "${docling_endpoint}/health" 60
echo "::endgroup::"

case "$suite" in
  core)
    echo "::group::Core Integration Tests"
    echo "${cyan}════════════════════════════════════════${nc}"
    echo "${purple} Core Integration Tests${nc}"
    echo "${cyan}════════════════════════════════════════${nc}"
    LOG_LEVEL="${LOG_LEVEL:-DEBUG}" \
      GOOGLE_OAUTH_CLIENT_ID="" \
      GOOGLE_OAUTH_CLIENT_SECRET="" \
      OPENSEARCH_HOST=localhost OPENSEARCH_PORT=9200 \
      LANGFLOW_OPENSEARCH_HOST=opensearch LANGFLOW_OPENSEARCH_PORT=9200 \
      OPENSEARCH_USERNAME=admin OPENSEARCH_PASSWORD="${OPENSEARCH_PASSWORD}" \
      DISABLE_STARTUP_INGEST="${DISABLE_STARTUP_INGEST:-true}" \
      uv run pytest tests/integration/core -vv -s -o log_cli=true --log-cli-level=DEBUG || test_result=1
    echo "::endgroup::"
    test_jwt_opensearch || test_result=1
    ;;
  sdk-python)
    wait_for_url "frontend at http://localhost:3000" "http://localhost:3000/" 60
    echo "::group::SDK Integration Tests (Python)"
    echo "${cyan}════════════════════════════════════════${nc}"
    echo "${purple} SDK Integration Tests (Python)${nc}"
    echo "${cyan}════════════════════════════════════════${nc}"
    uv pip install -e sdks/python
    SDK_TESTS_ONLY=true OPENRAG_URL=http://localhost:3000 uv run pytest tests/integration/sdk/ -vv -s || test_result=1
    echo "::endgroup::"
    ;;
  sdk-typescript)
    wait_for_url "frontend at http://localhost:3000" "http://localhost:3000/" 60
    echo "::group::SDK Integration Tests (TypeScript)"
    echo "${cyan}════════════════════════════════════════${nc}"
    echo "${purple} SDK Integration Tests (TypeScript)${nc}"
    echo "${cyan}════════════════════════════════════════${nc}"
    cd sdks/typescript
    npm install && npm run build && OPENRAG_URL=http://localhost:3000 npm test || test_result=1
    cd ../..
    echo "::endgroup::"
    ;;
  *)
    echo "${red}Unknown integration suite: ${suite}${nc}"
    test_result=1
    ;;
esac
