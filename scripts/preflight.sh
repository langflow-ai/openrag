#!/usr/bin/env bash
set -euo pipefail

# Preflight checks before production rollout.
# - Validates critical env vars
# - Checks backend/OpenSearch health
# - Verifies embedding vector dimension consistency

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_PATH="${ENV_PATH:-$ROOT_DIR/.env}"

if [[ -f "$ENV_PATH" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_PATH"
  set +a
fi

required_vars=(
  OPENSEARCH_PASSWORD
  OPENRAG_ENCRYPTION_KEY
  LANGFLOW_SECRET_KEY
  SESSION_SECRET
)

echo "==> Preflight: required variables"
for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: missing required variable: $var" >&2
    exit 1
  fi
  echo "OK: $var set"
done

FRONTEND_HEALTH_URL="${FRONTEND_HEALTH_URL:-http://127.0.0.1:${FRONTEND_PORT:-3000}/api/health}"
OS_HOST="${OPENSEARCH_HOST:-127.0.0.1}"
OS_PORT="${OPENSEARCH_PORT:-9200}"
OS_INDEX="${OPENSEARCH_INDEX_NAME:-documents}"

echo "==> Preflight: service health"
curl -fsS "$FRONTEND_HEALTH_URL" >/dev/null
echo "OK: frontend/backend health endpoint reachable"

curl -kfsS -u "admin:${OPENSEARCH_PASSWORD}" "https://${OS_HOST}:${OS_PORT}/_cluster/health" >/dev/null
echo "OK: OpenSearch health endpoint reachable"

echo "==> Preflight: embedding dimension check"
expected_dim=""
embedding_model="${EMBEDDING_MODEL:-}"
selected_model="${SELECTED_EMBEDDING_MODEL:-}"
model_for_dim="${selected_model:-$embedding_model}"

case "$model_for_dim" in
  nomic-embed-text) expected_dim="768" ;;
  text-embedding-3-small) expected_dim="1536" ;;
  text-embedding-3-large) expected_dim="3072" ;;
  "") expected_dim="" ;;
  *) expected_dim="" ;;
esac

mapping_json="$(curl -ksS -u "admin:${OPENSEARCH_PASSWORD}" "https://${OS_HOST}:${OS_PORT}/${OS_INDEX}/_mapping" || true)"
actual_dim="$(printf "%s" "$mapping_json" | python - <<'PY'
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    print("")
    raise SystemExit(0)
try:
    data = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)
if isinstance(data, dict) and "error" in data:
    print("")
    raise SystemExit(0)

def walk(node):
    if isinstance(node, dict):
        if "dimension" in node and isinstance(node["dimension"], int):
            return str(node["dimension"])
        for v in node.values():
            res = walk(v)
            if res:
                return res
    elif isinstance(node, list):
        for it in node:
            res = walk(it)
            if res:
                return res
    return ""

print(walk(data))
PY
)"

if [[ -z "$actual_dim" ]]; then
  echo "WARN: no vector dimension found in index '${OS_INDEX}' (index absent or no vectors yet)"
  echo "OK: preflight completed with warnings"
  exit 0
fi

if [[ -z "$expected_dim" ]]; then
  echo "WARN: unknown expected dimension for model '${model_for_dim:-unset}'"
  echo "INFO: index '${OS_INDEX}' reports dimension=${actual_dim}"
  echo "OK: preflight completed with warnings"
  exit 0
fi

if [[ "$actual_dim" != "$expected_dim" ]]; then
  echo "ERROR: embedding dimension mismatch (expected=${expected_dim}, actual=${actual_dim})" >&2
  echo "ACTION: re-ingest corpus after aligning EMBEDDING_MODEL / SELECTED_EMBEDDING_MODEL" >&2
  exit 1
fi

echo "OK: embedding dimension matches (${actual_dim})"
echo "OK: preflight completed successfully"
