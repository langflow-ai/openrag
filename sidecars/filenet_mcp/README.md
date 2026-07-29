# FileNet P8 MCP sidecar

OpenRAG-authored HTTP entry point for the
[IBM Content Services MCP Server](https://github.com/ibm-ecm/ibm-content-services-mcp-server),
exposing FileNet P8 (Content Manager) search + text-extract tools to the
OpenRAG chat agent over **streamable HTTP**.

Why this exists: every IBM console script hardcodes `mcp.run(transport="stdio")`,
so the package is consumed here as a *library*. `server.py` mirrors IBM's
`_run_server()` bootstrap for the **Core** config (the only one that registers
`document_search` and `get_document_text_extract`), then serves the FastMCP
instance over HTTP and adds two admin routes:

| Route | Purpose |
|---|---|
| `GET /health` | Process liveness (Kubernetes probe target). |
| `GET /diagnostics` | CPE reachability, `TxeTextExtractAnnotation` class presence (Persistent Text Extract add-on), `isCBREnabled` on the pinned class. Consumed by the OpenRAG backend startup diagnostic. |

## Environment

| Var | Required | Notes |
|---|---|---|
| `SERVER_URL` | yes | Content Services GraphQL URL, e.g. `https://<cpe-host>/content-services-graphql/graphql`. **Must not end with `/`** — a trailing slash silently breaks every text fetch (errors get returned *as document content*). The entry point hard-fails on it. |
| `OBJECT_STORE` | yes | The single object store this process is bound to (no tool searches across stores). |
| `USERNAME` | yes | CPD service account. Use a **dedicated least-privilege account**, never an admin — every chat user's query runs under this identity. |
| `PASSWORD` | yes | The account's **actual password**. CPD Basic auth rejects a Zen API key under `Basic`; for a revocable Zen credential use the IBM `ZENIAM_*` (Bearer) env set instead. |
| `SSL_ENABLED` | no | `true` (default) / `false` / path to a CA bundle. Prefer a CA bundle over `false` outside local dev. |
| `FILENET_MCP_HOST` / `FILENET_MCP_PORT` | no | Bind address, default `0.0.0.0:8811`. |
| `FILENET_MCP_AUTH_TOKEN` | no | Shared secret; when set, all routes except `/health` require `Authorization: Bearer <token>`. The OpenRAG backend registers the same token on the `filenet-p8` Langflow MCP server entry (`OPENRAG_FILENET_MCP_TOKEN`). |
| `FILENET_MCP_DOCUMENT_CLASS` | no | Class probed by `/diagnostics` (default `Document`). |
| `FILENET_MCP_STARTUP_RETRIES` / `FILENET_MCP_STARTUP_DELAY_SECONDS` | no | Bootstrap backoff (default 30 / 2.0s, exponential, capped at 30s). The IBM bootstrap performs a **live GraphQL call**, so readiness depends on CPE reachability. |

## Local dev

```bash
# From the repo root, with SERVER_URL/OBJECT_STORE/USERNAME/PASSWORD in .env:
make filenet-mcp-up      # builds Dockerfile.filenet-mcp, runs the compose profile
make filenet-mcp-down
```

Then point the backend at it:

```bash
OPENRAG_DEV_FILENET_MCP=true
OPENRAG_FILENET_MCP_URL=http://filenet-mcp:8811/mcp   # Langflow-container-resolvable; never localhost
```

### Spike / debugging without the image

```bash
SERVER_URL=https://<cpe-host>/content-services-graphql/graphql \
OBJECT_STORE=<OS> USERNAME=<user> PASSWORD=<password> LOG_LEVEL=DEBUG \
npx @modelcontextprotocol/inspector \
  uvx --from git+https://github.com/ibm-ecm/ibm-content-services-mcp-server core-cs-mcp-server
```

## Upgrade smoke check (run on every IBM ref bump)

This entry point depends on underscore-prefixed IBM internals with no
stability guarantee. `Dockerfile.filenet-mcp` pins `IBM_CS_MCP_REF` and the
image build asserts the required surface exists. When bumping the ref:

1. Build the image — the built-in `python -c` assertion must pass.
2. Re-read `cs_mcp_server/utils/utils.py::get_document_text_extract_content`
   and confirm the annotation filter is still `annotatedContentElement is not None`
   (a truthiness refactor would silently blank most corpora — real data returns `0`).
3. Re-read `client/graphql_client.py::download_text_async` and confirm the
   Mode-B sentinel string is still `Error: Failed to download text content` —
   the OpenRAG retrieve-and-window component prefix-matches it.
4. Run one end-to-end `document_search` + `get_document_text_extract` through
   MCP Inspector against a test object store.

## Security notes

- v1 uses a **single shared service identity**: per-user FileNet ACLs are NOT
  enforced per chat user. Requires governance sign-off before multi-tenant use.
- The account password is an unscoped, rotation-prone secret — store it in a
  Kubernetes Secret (Helm: `global.filenet.*`), never in a ConfigMap or image.
