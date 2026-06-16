#!/usr/bin/env bash
#
# test_openrag_auth.sh — diagnose OpenRAG SaaS auth: REST vs MCP JWT forwarding.
#
# Compares the REST surface (/api/v1/*) against the MCP surface (/mcp) using the
# same IBM credentials, then prints a verdict that maps to the known root causes
# of the "missing_user_jwt" failure on MCP tool calls.
#
# Usage:
#   ./test_openrag_auth.sh -b <base_url> -u <x-username> -k <x-api-key> [-q <query>]
#   ./test_openrag_auth.sh <base_url> <x-username> <x-api-key> [query]
#
# Exit code: 0 if MCP auth works, 1 if the MCP JWT-forwarding bug is present, 2 on usage error.

set -euo pipefail

QUERY="test"
BASE="" USERNAME="" APIKEY=""

# --- parse args (flags or positional) ---
if [[ "${1:-}" == -* ]]; then
  while getopts "b:u:k:q:h" opt; do
    case "$opt" in
      b) BASE="$OPTARG" ;;
      u) USERNAME="$OPTARG" ;;
      k) APIKEY="$OPTARG" ;;
      q) QUERY="$OPTARG" ;;
      h) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
      *) echo "bad option"; exit 2 ;;
    esac
  done
else
  BASE="${1:-}"; USERNAME="${2:-}"; APIKEY="${3:-}"; QUERY="${4:-test}"
fi

if [[ -z "$BASE" || -z "$USERNAME" || -z "$APIKEY" ]]; then
  echo "usage: $0 -b <base_url> -u <x-username> -k <x-api-key> [-q <query>]" >&2
  exit 2
fi
BASE="${BASE%/}"  # strip trailing slash

AUTH=(-H "x-username: $USERNAME" -H "x-api-key: $APIKEY")
JSON=(-H "Content-Type: application/json")
SSE=(-H "Accept: application/json, text/event-stream")
INIT_BODY='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test-script","version":"1.0"}}}'

redact() { local v="$1"; [[ -z "$v" ]] && { echo ""; return; }; echo "${v:0:3}…(len=${#v})"; }

echo "=================================================="
echo " OpenRAG auth diagnostic"
echo " base:     $BASE"
echo " username: $(redact "$USERNAME")"
echo " api-key:  $(redact "$APIKEY")"
echo "=================================================="

# --- 1. REST baseline: POST /api/v1/search ---
echo
echo "[1] REST  POST /api/v1/search"
REST_CODE=$(curl -sS -o /dev/null -w '%{http_code}' "${AUTH[@]}" "${JSON[@]}" -X POST \
  -d "{\"query\":\"$QUERY\",\"limit\":1}" "$BASE/api/v1/search" || echo "000")
echo "    -> HTTP $REST_CODE"

# --- helper: full MCP handshake against an endpoint, echo the tools/call result text ---
mcp_call() {
  local ep="$1" sid body
  sid=$(curl -sS -D - -o /dev/null "${AUTH[@]}" "${JSON[@]}" "${SSE[@]}" -X POST \
        -d "$INIT_BODY" "$BASE$ep" 2>/dev/null \
        | tr -d '\r' | awk 'tolower($1)=="mcp-session-id:"{print $2}')
  if [[ -z "$sid" ]]; then echo "NO_SESSION"; return; fi
  curl -sS -o /dev/null "${AUTH[@]}" "${JSON[@]}" "${SSE[@]}" -H "mcp-session-id: $sid" -X POST \
    -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' "$BASE$ep" >/dev/null 2>&1 || true
  body=$(curl -sS "${AUTH[@]}" "${JSON[@]}" "${SSE[@]}" -H "mcp-session-id: $sid" -X POST \
    -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"openrag_search\",\"arguments\":{\"query\":\"$QUERY\",\"limit\":1}}}" \
    "$BASE$ep" 2>/dev/null)
  # strip SSE framing -> just the data payload
  echo "$body" | sed -n 's/^data: //p' | tail -n1
}

classify() {  # arg: tools/call result text -> PASS / MISSING_JWT / OTHER / NO_SESSION
  local r="$1"
  if [[ "$r" == "NO_SESSION" ]]; then echo "NO_SESSION";
  elif grep -q "missing_user_jwt" <<<"$r"; then echo "MISSING_JWT";
  elif grep -q "invalid_jwt" <<<"$r"; then echo "INVALID_JWT";
  elif grep -q '"isError":true' <<<"$r"; then echo "TOOL_ERROR";
  elif grep -q '"result"' <<<"$r"; then echo "PASS";
  else echo "OTHER"; fi
}

echo
echo "[2] MCP   /mcp        (initialize -> tools/call openrag_search)"
R_MCP=$(mcp_call "/mcp"); C_MCP=$(classify "$R_MCP")
echo "    -> $C_MCP"
[[ "$C_MCP" != "PASS" ]] && echo "    $(echo "$R_MCP" | head -c 240)"

echo
echo "[3] MCP   /api/mcp    (path-prefix discriminator)"
R_API=$(mcp_call "/api/mcp"); C_API=$(classify "$R_API")
echo "    -> $C_API"
[[ "$C_API" != "PASS" ]] && echo "    $(echo "$R_API" | head -c 240)"

echo
echo "[4] Redirects on /mcp"
NRD=$(curl -sS -L -o /dev/null -w '%{num_redirects}' "${AUTH[@]}" "${JSON[@]}" "${SSE[@]}" -X POST \
  -d "$INIT_BODY" "$BASE/mcp" 2>/dev/null || echo "?")
echo "    -> num_redirects=$NRD"

# --- verdict ---
echo
echo "=================================================="
echo " VERDICT"
echo "=================================================="
if [[ "$REST_CODE" == "200" && "$C_MCP" == "PASS" ]]; then
  echo " [OK] REST and MCP both authenticate. JWT forwarding is healthy."
  exit 0
elif [[ "$REST_CODE" == "200" && "$C_MCP" == "MISSING_JWT" && "$C_API" == "MISSING_JWT" ]]; then
  echo " [BUG] REST works (200) but MCP fails (missing_user_jwt) on both /mcp and /api/mcp."
  echo "       => Gateway is delivering the JWT in 'Authorization' (read by REST,"
  echo "          STRIPPED by FastMCP), and NOT injecting 'X-OpenRAG-API-JWT'."
  echo "       FIX: Traefik must inject X-OpenRAG-API-JWT (with full role claims) on"
  echo "            MCP-bound traffic via authResponseHeaders."
  exit 1
elif [[ "$REST_CODE" == "200" && "$C_MCP" == "MISSING_JWT" && "$C_API" == "PASS" ]]; then
  echo " [BUG] MCP fails on /mcp but works on /api/mcp."
  echo "       => Gateway JWT injection is path-scoped to /api and misses /mcp."
  exit 1
elif [[ "$C_MCP" == "INVALID_JWT" || "$C_API" == "INVALID_JWT" ]]; then
  echo " [WARN] JWT arrives but fails decode/verify (expired / wrong key / malformed)."
  echo "        Not a 'missing header' problem — check token minting & signature config."
  exit 1
else
  echo " [WARN] Unexpected state — REST=$REST_CODE  /mcp=$C_MCP  /api/mcp=$C_API"
  echo "        Inspect raw outputs above."
  exit 1
fi
