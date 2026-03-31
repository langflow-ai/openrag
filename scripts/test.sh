#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════
# OpenSearch ACL Test Script
# Tests Document-Level Security (DLS) by searching existing documents
# ═══════════════════════════════════════════════════════════

OS_URL="${OS_URL:?Set OS_URL (e.g. https://host:9200)}"
USER_A="${USER_A:?Set USER_A (user:password for first user)}"
USER_B="${USER_B:?Set USER_B (user:password for second user)}"
INDEX="${INDEX:-documents}"

# Actual user identity used as document owner (may differ from API key username)
USER_A_NAME="${USER_A_OWNER:?Set USER_A_OWNER (e.g. ming.luo@ibm.com)}"
USER_B_NAME="${USER_B_OWNER:?Set USER_B_OWNER (e.g. AKHILDEV@ibm.com)}"

PASS=0
FAIL=0

green()  { printf "\033[32m%s\033[0m\n" "$*"; }
red()    { printf "\033[31m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
bold()   { printf "\033[1m%s\033[0m\n" "$*"; }
dim()    { printf "\033[2m%s\033[0m\n" "$*"; }

check() {
    local label="$1" expected="$2" actual="$3"
    if [ "$actual" = "$expected" ]; then
        green "  ✓ $label (expected=$expected, got=$actual)"
        PASS=$((PASS + 1))
    else
        red "  ✗ $label (expected=$expected, got=$actual)"
        FAIL=$((FAIL + 1))
    fi
}

curl_os() {
    local creds="$1"; shift
    curl -sk -u "$creds" "$@"
}

# ───────────────────────────────────────────────
bold "Step 0: Cluster health"
# ───────────────────────────────────────────────

HEALTH=$(curl_os "$USER_A" "$OS_URL/_cluster/health" 2>/dev/null)
echo "$HEALTH" | python3 -c "
import sys, json
h = json.load(sys.stdin)
status = h.get('status', 'unknown')
color = {'green': '\033[32m', 'yellow': '\033[33m', 'red': '\033[31m'}.get(status, '')
reset = '\033[0m'
print(f'  Status:              {color}{status}{reset}')
print(f'  Cluster name:        {h.get(\"cluster_name\", \"?\")}')
print(f'  Nodes:               {h.get(\"number_of_nodes\", \"?\")}')
print(f'  Data nodes:          {h.get(\"number_of_data_nodes\", \"?\")}')
print(f'  Active shards:       {h.get(\"active_shards\", \"?\")}')
print(f'  Relocating shards:   {h.get(\"relocating_shards\", \"?\")}')
print(f'  Unassigned shards:   {h.get(\"unassigned_shards\", \"?\")}')
print(f'  Pending tasks:       {h.get(\"number_of_pending_tasks\", \"?\")}')
" 2>/dev/null || red "  Could not fetch cluster health"
echo ""

# ───────────────────────────────────────────────
bold "Step 1: Verify authentication"
# ───────────────────────────────────────────────

echo "User A ($USER_A_NAME):"
ACCT_A=$(curl_os "$USER_A" "$OS_URL/_plugins/_security/api/account" 2>/dev/null)
ROLES_A=$(echo "$ACCT_A" | python3 -c "import sys,json; print(','.join(json.load(sys.stdin).get('roles',[])))" 2>/dev/null || echo "PARSE_ERROR")
BROLES_A=$(echo "$ACCT_A" | python3 -c "import sys,json; print(','.join(json.load(sys.stdin).get('backend_roles',[])))" 2>/dev/null || echo "PARSE_ERROR")
echo "  roles: $ROLES_A"
echo "  backend_roles: $BROLES_A"
if [ "$ROLES_A" = "PARSE_ERROR" ]; then
    red "  ERROR: could not parse account info. Raw response:"
    dim "  $ACCT_A"
fi

echo "User B ($USER_B_NAME):"
ACCT_B=$(curl_os "$USER_B" "$OS_URL/_plugins/_security/api/account" 2>/dev/null)
ROLES_B=$(echo "$ACCT_B" | python3 -c "import sys,json; print(','.join(json.load(sys.stdin).get('roles',[])))" 2>/dev/null || echo "PARSE_ERROR")
BROLES_B=$(echo "$ACCT_B" | python3 -c "import sys,json; print(','.join(json.load(sys.stdin).get('backend_roles',[])))" 2>/dev/null || echo "PARSE_ERROR")
echo "  roles: $ROLES_B"
echo "  backend_roles: $BROLES_B"
if [ "$ROLES_B" = "PARSE_ERROR" ]; then
    red "  ERROR: could not parse account info. Raw response:"
    dim "  $ACCT_B"
fi

if echo "$ROLES_A" | grep -q "all_access"; then
    yellow "  ⚠ User A has all_access — OpenSearch DLS will be bypassed"
fi
if echo "$ROLES_B" | grep -q "all_access"; then
    yellow "  ⚠ User B has all_access — OpenSearch DLS will be bypassed"
fi
echo ""

# ───────────────────────────────────────────────
bold "Step 2: List indices & check mapping"
# ───────────────────────────────────────────────

echo "  All indices on cluster:"
curl_os "$USER_A" "$OS_URL/_cat/indices?format=json" 2>/dev/null \
    | python3 -c "
import sys, json
indices = json.load(sys.stdin)
indices.sort(key=lambda x: int(x.get('docs.count') or 0), reverse=True)
for idx in indices:
    name = idx.get('index', '?')
    cnt = idx.get('docs.count', '0') or '0'
    sz = idx.get('store.size', '?') or '?'
    if int(cnt) > 0:
        print(f'    \033[32m{name:<40}  docs={cnt}  size={sz}\033[0m')
    else:
        print(f'    {name:<40}  docs={cnt}  size={sz}')
" 2>/dev/null
echo ""

INDEX_STATUS=$(curl_os "$USER_A" -o /dev/null -w "%{http_code}" "$OS_URL/$INDEX" 2>/dev/null || echo "000")
if [ "$INDEX_STATUS" = "200" ]; then
    green "  Index '$INDEX' exists"
else
    red "  Index '$INDEX' does NOT exist (HTTP $INDEX_STATUS)"
    echo "  Available indices:"
    curl_os "$USER_A" "$OS_URL/_cat/indices?v&h=index,docs.count,store.size" 2>/dev/null | while IFS= read -r line; do echo "    $line"; done
    exit 1
fi

MAPPING_RAW=$(curl_os "$USER_A" "$OS_URL/$INDEX/_mapping" 2>/dev/null)
OWNER_TYPE=$(echo "$MAPPING_RAW" | python3 -c "
import sys, json
m = json.load(sys.stdin)
for idx in m.values():
    props = idx.get('mappings',{}).get('properties',{})
    print(props.get('owner',{}).get('type','MISSING'))
    break
" 2>/dev/null || echo "PARSE_ERROR")
ALLOWED_TYPE=$(echo "$MAPPING_RAW" | python3 -c "
import sys, json
m = json.load(sys.stdin)
for idx in m.values():
    props = idx.get('mappings',{}).get('properties',{})
    print(props.get('allowed_users',{}).get('type','MISSING'))
    break
" 2>/dev/null || echo "PARSE_ERROR")

check "owner field type is keyword" "keyword" "$OWNER_TYPE"
check "allowed_users field type is keyword" "keyword" "$ALLOWED_TYPE"
echo ""

parse_search_count() {
    python3 -c "import sys,json; print(json.load(sys.stdin).get('hits',{}).get('total',{}).get('value',-1))" 2>/dev/null || echo "-1"
}

# ───────────────────────────────────────────────
bold "Step 3: Document overview"
# ───────────────────────────────────────────────

OVERVIEW=$(curl_os "$USER_A" -H "Content-Type: application/json" \
    -X POST "$OS_URL/$INDEX/_search" \
    -d '{
        "size": 0,
        "query": {"match_all": {}},
        "aggs": {
            "owners": {"terms": {"field": "owner", "size": 50}},
            "no_owner": {"missing": {"field": "owner"}}
        }
    }' 2>/dev/null)

TOTAL=$(echo "$OVERVIEW" | parse_search_count)
echo "  Total documents in index: $TOTAL"

echo "  Documents by owner:"
echo "$OVERVIEW" | python3 -c "
import sys, json
data = json.load(sys.stdin)
aggs = data.get('aggregations', {})
buckets = aggs.get('owners', {}).get('buckets', [])
for b in buckets:
    print(f'    {b[\"key\"]}: {b[\"doc_count\"]} docs')
no_owner = aggs.get('no_owner', {}).get('doc_count', 0)
if no_owner:
    print(f'    (no owner): {no_owner} docs')
" 2>/dev/null || yellow "  Could not parse owner aggregation"
echo ""

# ───────────────────────────────────────────────
bold "Step 4: Search as each user (DLS test)"
# ───────────────────────────────────────────────

echo "User A ($USER_A_NAME) — unfiltered search:"
RESULT_A=$(curl_os "$USER_A" -H "Content-Type: application/json" \
    -X POST "$OS_URL/$INDEX/_search" \
    -d '{"size":0,"query":{"match_all":{}}}' 2>/dev/null)
COUNT_A=$(echo "$RESULT_A" | parse_search_count)
echo "  Docs visible: $COUNT_A"
if [ "$COUNT_A" = "-1" ]; then
    yellow "  Debug — raw response:"
    dim "  $(echo "$RESULT_A" | head -c 500)"
fi

echo "User B ($USER_B_NAME) — unfiltered search:"
RESULT_B=$(curl_os "$USER_B" -H "Content-Type: application/json" \
    -X POST "$OS_URL/$INDEX/_search" \
    -d '{"size":0,"query":{"match_all":{}}}' 2>/dev/null)
COUNT_B=$(echo "$RESULT_B" | parse_search_count)
echo "  Docs visible: $COUNT_B"
if [ "$COUNT_B" = "-1" ]; then
    yellow "  Debug — raw response:"
    dim "  $(echo "$RESULT_B" | head -c 500)"
fi

if [ "$COUNT_A" = "$COUNT_B" ] && [ "$COUNT_A" = "$TOTAL" ]; then
    yellow "  ⚠ Both users see ALL $TOTAL docs — DLS is NOT filtering (likely all_access)"
elif [ "$COUNT_A" != "$COUNT_B" ]; then
    green "  ✓ Users see different doc counts — DLS appears to be working"
fi
echo ""

echo "User A — owners visible:"
curl_os "$USER_A" -H "Content-Type: application/json" \
    -X POST "$OS_URL/$INDEX/_search" \
    -d '{"size":0,"query":{"match_all":{}},"aggs":{"owners":{"terms":{"field":"owner","size":50}},"no_owner":{"missing":{"field":"owner"}}}}' 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
aggs = data.get('aggregations', {})
for b in aggs.get('owners', {}).get('buckets', []):
    print(f'    {b[\"key\"]}: {b[\"doc_count\"]}')
no_owner = aggs.get('no_owner', {}).get('doc_count', 0)
if no_owner:
    print(f'    (no owner): {no_owner}')
" 2>/dev/null || yellow "  Could not parse"

echo "User B — owners visible:"
curl_os "$USER_B" -H "Content-Type: application/json" \
    -X POST "$OS_URL/$INDEX/_search" \
    -d '{"size":0,"query":{"match_all":{}},"aggs":{"owners":{"terms":{"field":"owner","size":50}},"no_owner":{"missing":{"field":"owner"}}}}' 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
aggs = data.get('aggregations', {})
for b in aggs.get('owners', {}).get('buckets', []):
    print(f'    {b[\"key\"]}: {b[\"doc_count\"]}')
no_owner = aggs.get('no_owner', {}).get('doc_count', 0)
if no_owner:
    print(f'    (no owner): {no_owner}')
" 2>/dev/null || yellow "  Could not parse"
echo ""

# ───────────────────────────────────────────────
bold "Step 5: Application-level ACL filter"
# ───────────────────────────────────────────────

echo "User A ($USER_A_NAME) — with ACL filter:"
APP_RESULT_A=$(curl_os "$USER_A" -H "Content-Type: application/json" \
    -X POST "$OS_URL/$INDEX/_search" \
    -d "{
        \"size\":0,
        \"query\":{
            \"bool\":{
                \"should\":[
                    {\"term\":{\"owner\":\"$USER_A_NAME\"}},
                    {\"term\":{\"allowed_users\":\"$USER_A_NAME\"}},
                    {\"bool\":{\"must_not\":{\"exists\":{\"field\":\"owner\"}}}}
                ],
                \"minimum_should_match\":1
            }
        }
    }" 2>/dev/null)
APP_COUNT_A=$(echo "$APP_RESULT_A" | parse_search_count)
echo "  Docs visible: $APP_COUNT_A"
if [ "$APP_COUNT_A" = "-1" ]; then
    yellow "  Debug — raw response:"
    dim "  $(echo "$APP_RESULT_A" | head -c 500)"
fi

echo "User B ($USER_B_NAME) — with ACL filter:"
APP_RESULT_B=$(curl_os "$USER_B" -H "Content-Type: application/json" \
    -X POST "$OS_URL/$INDEX/_search" \
    -d "{
        \"size\":0,
        \"query\":{
            \"bool\":{
                \"should\":[
                    {\"term\":{\"owner\":\"$USER_B_NAME\"}},
                    {\"term\":{\"allowed_users\":\"$USER_B_NAME\"}},
                    {\"bool\":{\"must_not\":{\"exists\":{\"field\":\"owner\"}}}}
                ],
                \"minimum_should_match\":1
            }
        }
    }" 2>/dev/null)
APP_COUNT_B=$(echo "$APP_RESULT_B" | parse_search_count)
echo "  Docs visible: $APP_COUNT_B"
if [ "$APP_COUNT_B" = "-1" ]; then
    yellow "  Debug — raw response:"
    dim "  $(echo "$APP_RESULT_B" | head -c 500)"
fi

echo ""
if [ "$APP_COUNT_A" != "$APP_COUNT_B" ]; then
    green "  ✓ App-level filter: users see different counts (A=$APP_COUNT_A, B=$APP_COUNT_B)"
    check "App filter reduces User A's visible docs" "true" \
        "$([ "$APP_COUNT_A" -lt "$COUNT_A" ] 2>/dev/null && echo true || echo false)"
    check "App filter reduces User B's visible docs" "true" \
        "$([ "$APP_COUNT_B" -lt "$COUNT_B" ] 2>/dev/null && echo true || echo false)"
elif [ "$APP_COUNT_A" = "0" ] && [ "$APP_COUNT_B" = "0" ]; then
    red "  ✗ Both users see 0 docs — owner field may not match usernames"
    echo ""
    yellow "  Owner values in index vs. usernames used in filter:"
    yellow "    User A owner: $USER_A_NAME"
    yellow "    User B owner: $USER_B_NAME"
    yellow "    Owner values in index: (see Step 3 above)"
    yellow "  If these don't match, the term query won't find anything."
else
    yellow "  ⚠ Both users see same count ($APP_COUNT_A) — check owner field values"
fi
echo ""

# ───────────────────────────────────────────────
bold "Step 6: Sample documents (first 3)"
# ───────────────────────────────────────────────

echo "User A — sample docs:"
curl_os "$USER_A" -H "Content-Type: application/json" \
    -X POST "$OS_URL/$INDEX/_search" \
    -d '{"query":{"match_all":{}},"_source":["document_id","filename","owner","allowed_users"],"size":3}' 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
for h in data.get('hits',{}).get('hits',[]):
    s = h.get('_source',{})
    print(f'    id={h[\"_id\"][:30]}  owner={s.get(\"owner\",\"NONE\")}  allowed={s.get(\"allowed_users\",[])}  file={s.get(\"filename\",\"?\")}')
" 2>/dev/null || yellow "  Could not parse"

echo "User B — sample docs:"
curl_os "$USER_B" -H "Content-Type: application/json" \
    -X POST "$OS_URL/$INDEX/_search" \
    -d '{"query":{"match_all":{}},"_source":["document_id","filename","owner","allowed_users"],"size":3}' 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
for h in data.get('hits',{}).get('hits',[]):
    s = h.get('_source',{})
    print(f'    id={h[\"_id\"][:30]}  owner={s.get(\"owner\",\"NONE\")}  allowed={s.get(\"allowed_users\",[])}  file={s.get(\"filename\",\"?\")}')
" 2>/dev/null || yellow "  Could not parse"
echo ""

# ───────────────────────────────────────────────
bold "═══ Results ═══"
# ───────────────────────────────────────────────
echo "  Total in index:                $TOTAL"
echo "  User A unfiltered:             $COUNT_A"
echo "  User B unfiltered:             $COUNT_B"
echo "  User A with app ACL filter:    $APP_COUNT_A"
echo "  User B with app ACL filter:    $APP_COUNT_B"
echo ""
green "  Passed: $PASS"
if [ "$FAIL" -gt 0 ]; then
    red "  Failed: $FAIL"
    exit 1
else
    echo "  Failed: 0"
    green "  All checks passed!"
fi
