# MCP auth diagnostic

`test_openrag_auth.sh` diagnoses why MCP tool calls fail with
`missing_user_jwt` on a SaaS/IBM OpenRAG deployment while the REST API works.

It uses the same IBM credentials (`X-Username` + `X-Api-Key`) against both
surfaces and compares the results:

- **REST** — `POST /api/v1/search`
- **MCP** — full streamable-HTTP handshake (`initialize` → `notifications/initialized`
  → `tools/call openrag_search`) on `/mcp` **and** `/api/mcp`

## Why both surfaces?

On a SaaS deployment the gateway (Traefik) authenticates the
`X-Username`/`X-Api-Key` pair and is expected to inject the minted end-user JWT
into the `X-OpenRAG-API-JWT` header. The two surfaces read that JWT differently:

| Surface | How the JWT reaches the `/v1` auth dependency |
| --- | --- |
| REST `/api/v1/*` | Read directly from `Authorization`, else `X-OpenRAG-API-JWT`. |
| MCP `/mcp` | FastMCP proxies the tool call to `/v1` in-process and **strips `Authorization`**, forwarding only `X-OpenRAG-API-JWT`. |

So if the gateway injects the JWT into `Authorization` only, REST succeeds but
every MCP tool call fails with `missing_user_jwt` — because FastMCP drops
`Authorization` and there is no `X-OpenRAG-API-JWT` to fall back to.

The `/api/mcp` probe is a discriminator: `/api/mcp` and `/mcp` hit the same
backend MCP server but Traefik sees different path prefixes (`/api` vs `/mcp`).
Comparing them separates a path-scoped gateway middleware from a wrong-header
injection.

## Usage

```bash
./test_openrag_auth.sh -b <base_url> -u <x-username> -k <x-api-key> [-q <query>]
# or positional:
./test_openrag_auth.sh <base_url> <x-username> <x-api-key> [query]
```

Example:

```bash
./scripts/mcp_test/test_openrag_auth.sh \
  -b https://<deployment-id>.lakehouse.dev.ibmappdomain.cloud \
  -u ibmlhapikey_you@example.com \
  -k <your-api-key>
```

## Output

The script prints each probe's result and a final verdict. Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | REST and MCP both authenticate — JWT forwarding is healthy. |
| `1` | MCP JWT-forwarding bug present (or invalid/expired JWT). |
| `2` | Usage error (missing arguments). |

Verdicts map to root causes:

- **REST 200 + MCP `missing_user_jwt` on both paths** → gateway delivers the JWT
  via `Authorization` only; fix Traefik to also inject `X-OpenRAG-API-JWT`
  (with the user's full role claims) on MCP traffic.
- **REST 200 + `/mcp` fails but `/api/mcp` passes** → gateway JWT injection is
  path-scoped to `/api` and misses `/mcp`.
- **`invalid_jwt`** → the JWT arrives but fails decode/verify (expired, wrong
  signing key, or malformed) — not a missing-header problem.

## Requirements

`bash` + `curl` and coreutils (`grep`, `sed`, `awk`). No `jq` needed.

## Notes

- Credentials are redacted in the printed header (first 3 chars + length); pass
  them as arguments and avoid committing them to shell history.
- The role claims carried by the JWT matter: a reduced-role MCP token re-syncs
  the shared DB user row down on every `/v1` call, which can revoke a UI user's
  permissions. Ensure the gateway mints the same full-role JWT used by the UI
  session.
