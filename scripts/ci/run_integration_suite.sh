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

# Load variables from env file to find COMPOSE_PROJECT_NAME and OPENSEARCH_PORT
COMPOSE_PROJECT_NAME=""
OPENSEARCH_PORT=""
LANGFLOW_PORT=""
if [[ -f "$env_file" ]]; then
  COMPOSE_PROJECT_NAME="$(grep -E '^COMPOSE_PROJECT_NAME=' "$env_file" | cut -d= -f2- | tr -d '"'\')"
  OPENSEARCH_PORT="$(grep -E '^OPENSEARCH_PORT=' "$env_file" | cut -d= -f2- | tr -d '"'\')"
  LANGFLOW_PORT="$(grep -E '^LANGFLOW_PORT=' "$env_file" | cut -d= -f2- | tr -d '"'\')"
fi

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-openrag}"
OPENSEARCH_PORT="${OPENSEARCH_PORT:-9200}"
LANGFLOW_PORT="${LANGFLOW_PORT:-7860}"

compose_cmd+=("-p" "$COMPOSE_PROJECT_NAME")

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
    https://localhost:${OPENSEARCH_PORT}/documents/_search \
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
  echo "${red}=== Tests failed, saving container logs to service-logs/ ===${nc}"
  mkdir -p service-logs

  redact() {
    local pw="${OPENSEARCH_PASSWORD:-__unset__}"
    pw=$(printf '%s\n' "$pw" | sed -E 's/([][\\/.*+?^$|()])/\\\1/g')
    sed -E -e 's/Bearer [A-Za-z0-9._-]+/Bearer **REDACTED**/g' \
           -e 's/token=[A-Za-z0-9._-]+/token=**REDACTED**/g' \
           -e 's/sk-[A-Za-z0-9._-]+/sk-**REDACTED**/g' \
           -e "s/${pw}/**REDACTED**/g"
  }

  "$container_runtime" logs --tail 10000 "${COMPOSE_PROJECT_NAME}-langflow" 2>&1 | redact > service-logs/langflow.log || echo "${red}Could not get Langflow logs${nc}"
  "$container_runtime" logs --tail 10000 "${COMPOSE_PROJECT_NAME}-backend" 2>&1 | redact > service-logs/backend.log || echo "${red}Could not get backend logs${nc}"
  "$container_runtime" logs --tail 10000 "${COMPOSE_PROJECT_NAME}-frontend" 2>&1 | redact > service-logs/frontend.log || echo "${red}Could not get frontend logs${nc}"
  "$container_runtime" logs --tail 10000 "${COMPOSE_PROJECT_NAME}-opensearch" 2>&1 | redact > service-logs/opensearch.log || echo "${red}Could not get OpenSearch logs${nc}"
  if [[ -f ~/.openrag/tui/docling-serve.log ]]; then
    redact < ~/.openrag/tui/docling-serve.log > service-logs/docling.log || echo "${red}Could not get Docling logs${nc}"
  fi
}

generate_report() {
  uv run python scripts/ci/generate_test_report.py service-logs || true
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" && -f service-logs/test-failure-report.md ]]; then
    cat service-logs/test-failure-report.md >> "$GITHUB_STEP_SUMMARY"
  fi
}

teardown() {
  local status=$?
  if [[ "$status" -ne 0 && "$test_result" -eq 0 ]]; then
    test_result="$status"
  fi

  generate_report || true

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
uv sync --quiet --group dev

echo "::group::Start Infrastructure"
echo "${yellow}Cleaning up old containers and volumes...${nc}"
"${compose_cmd[@]}" down -v 2>/dev/null || true

echo "${yellow}Starting infra for suite '${suite}' with OpenRAG version '${OPENRAG_VERSION:-latest}'${nc}"
OPENSEARCH_HOST=opensearch "${compose_cmd[@]}" up -d opensearch langflow openrag-backend openrag-frontend

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
  if "${compose_cmd[@]}" exec -T openrag-backend curl -s http://localhost:8000/.well-known/openid-configuration >/dev/null 2>&1; then
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
  if "${compose_cmd[@]}" logs opensearch 2>&1 | grep -q "Security configuration applied successfully"; then
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
  authc_config="$(curl -k -s -u "admin:${OPENSEARCH_PASSWORD}" https://localhost:${OPENSEARCH_PORT}/_opendistro/_security/api/securityconfig 2>/dev/null || true)"
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

wait_for_url "Langflow" "http://localhost:${LANGFLOW_PORT}/" 60
wait_for_url "docling-serve at ${docling_endpoint}" "${docling_endpoint}/health" 60
echo "::endgroup::"

mkdir -p service-logs

case "$suite" in
  core)
    echo "::group::Core Integration Tests"
    echo "${cyan}════════════════════════════════════════${nc}"
    echo "${purple} Core Integration Tests${nc}"
    echo "${cyan}════════════════════════════════════════${nc}"
    mkdir -p service-logs
    LOG_LEVEL="${LOG_LEVEL:-DEBUG}" \
      GOOGLE_OAUTH_CLIENT_ID="" \
      GOOGLE_OAUTH_CLIENT_SECRET="" \
      OPENSEARCH_HOST=localhost OPENSEARCH_PORT=${OPENSEARCH_PORT} \
      OPENSEARCH_USERNAME=admin OPENSEARCH_PASSWORD="${OPENSEARCH_PASSWORD}" \
      DISABLE_STARTUP_INGEST="${DISABLE_STARTUP_INGEST:-true}" \
      uv run pytest tests/integration/core -vv -s --log-file=service-logs/pytest-core.log --log-file-level=DEBUG --junitxml=service-logs/junit-core.xml || test_result=1
    echo "::endgroup::"
    test_jwt_opensearch || test_result=1
    ;;
  sdk-python)
    wait_for_url "frontend at http://localhost:3000" "http://localhost:3000/" 60
    echo "::group::SDK Integration Tests (Python)"
    echo "${cyan}════════════════════════════════════════${nc}"
    echo "${purple} SDK Integration Tests (Python)${nc}"
    echo "${cyan}════════════════════════════════════════${nc}"
    uv pip install --quiet -e sdks/python
    SDK_TESTS_ONLY=true OPENRAG_URL=http://localhost:3000 uv run pytest tests/integration/sdk/ -vv -s --log-file=service-logs/pytest-sdk.log --log-file-level=DEBUG --junitxml=service-logs/junit-sdk-python.xml || test_result=1
    echo "::endgroup::"
    ;;
  sdk-typescript)
    wait_for_url "frontend at http://localhost:3000" "http://localhost:3000/" 60
    echo "::group::SDK Integration Tests (TypeScript)"
    echo "${cyan}════════════════════════════════════════${nc}"
    echo "${purple} SDK Integration Tests (TypeScript)${nc}"
    echo "${cyan}════════════════════════════════════════${nc}"
    cd sdks/typescript
    npm install && npm run build && OPENRAG_URL=http://localhost:3000 npm test -- --reporter=junit --outputFile=../../service-logs/junit-sdk-typescript.xml || test_result=1
    cd ../..
    echo "::endgroup::"
    ;;
  *)
    echo "${red}Unknown integration suite: ${suite}${nc}"
    test_result=1
    ;;
esac
