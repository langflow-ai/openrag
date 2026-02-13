# OpenRAG MCP Server

An [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that exposes your OpenRAG knowledge base to AI assistants. It lets MCP-compatible apps like Cursor, Claude Desktop, and IBM Watson Orchestrate use OpenRAG’s RAG capabilities (chat, search, settings) over a standard protocol—no custom integrations per platform.

---

## What is OpenRAG MCP?

OpenRAG MCP is a **connectivity layer** between your OpenRAG instance and AI applications. The host app (e.g. Cursor or Claude Desktop) runs the MCP server as a subprocess and talks to it over stdio using JSON-RPC. The server then calls your OpenRAG API with your API key. Your knowledge base stays the single source of truth; all connected apps get the same RAG-backed chat and search.

---

## Quick Start

Run the server with **uvx** (no local install required; requires Python 3.10+ and [uv](https://docs.astral.sh/uv/)):

```bash
uvx openrag-mcp
```

Set required environment variables first (or pass them via your MCP client config):

```bash
export OPENRAG_URL="https://your-openrag-instance.com"
export OPENRAG_API_KEY="orag_your_api_key"
uvx openrag-mcp
```

To pin a version:

```bash
uvx --from openrag-mcp==0.2.1 openrag-mcp
```

### Prerequisites

- Python 3.10+
- A running OpenRAG instance
- An OpenRAG API key (create one in **Settings → API Keys** in OpenRAG)
- `uv` installed (for `uvx`)

---

## Available Tools

These tools are currently exposed by the server:

| Tool | Description |
|:-----|:------------|
| `openrag_chat` | Send a message and get a RAG-enhanced response. Optional: `chat_id`, `filter_id`, `limit`, `score_threshold`. |
| `openrag_search` | Semantic search over the knowledge base. Optional: `limit`, `score_threshold`, `filter_id`, `data_sources`, `document_types`. |
| `openrag_get_settings` | Get current OpenRAG configuration (LLM, embeddings, chunk settings, system prompt, etc.). |
| `openrag_update_settings` | Update OpenRAG configuration (LLM model, embedding model, chunk size/overlap, system prompt, table structure, OCR, picture descriptions). |
| `openrag_list_models` | List available language and embedding models for a provider (`openai`, `anthropic`, `ollama`, `watsonx`). |

### Coming later (document tools)

Document ingestion and management tools (`openrag_ingest_file`, `openrag_ingest_url`, `openrag_delete_document`, `openrag_get_task_status`, `openrag_wait_for_task`) are implemented but not yet registered in this server; they will be enabled in a future release.

---

## Environment Variables

| Variable | Description | Required | Default |
|:---------|:------------|:--------:|:--------|
| `OPENRAG_API_KEY` | Your OpenRAG API key | Yes | — |
| `OPENRAG_URL` | Base URL of your OpenRAG instance | No | `http://localhost:3000` |

**MCP HTTP client (optional):**

| Variable | Description | Required | Default |
|:---------|:------------|:--------:|:--------|
| `OPENRAG_MCP_TIMEOUT` | Request timeout in seconds | No | `60.0` |
| `OPENRAG_MCP_MAX_CONNECTIONS` | Maximum concurrent connections | No | `100` |
| `OPENRAG_MCP_MAX_KEEPALIVE_CONNECTIONS` | Maximum keepalive connections | No | `20` |
| `OPENRAG_MCP_MAX_RETRIES` | Maximum retry attempts for failed requests | No | `3` |
| `OPENRAG_MCP_FOLLOW_REDIRECTS` | Whether to follow HTTP redirects | No | `true` |

These must be set in the environment when the MCP server runs (e.g. in the `env` block of your MCP client config).

---

## How to Use

### Cursor

**Config file:** `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "openrag": {
      "command": "uvx",
      "args": ["openrag-mcp"],
      "env": {
        "OPENRAG_URL": "https://your-openrag-instance.com",
        "OPENRAG_API_KEY": "orag_your_api_key_here"
      }
    }
  }
}
```

Restart Cursor after changing the config.

### Claude Desktop

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "openrag": {
      "command": "uvx",
      "args": ["openrag-mcp"],
      "env": {
        "OPENRAG_URL": "https://your-openrag-instance.com",
        "OPENRAG_API_KEY": "orag_your_api_key_here"
      }
    }
  }
}
```

Restart Claude Desktop after editing the file.

---

## Run from source (development)

To use the **latest MCP code** from the repo (including settings and models tools), run from source. Do **not** install the package if you want local edits to apply.

### Steps

| Step | What | Command | Required for |
|------|------|---------|---------------|
| 1 | OpenRAG backend | Run your OpenRAG app (e.g. frontend + API) | All tools |
| 2 | MCP from source | `cd sdks/mcp && uv sync` | All tools; no wheel needed |
| 3 | (Optional) SDK from repo | `cd sdks/python && uv pip install -e .` | Only if you need unreleased chat/search SDK changes |

Settings and models tools (`openrag_get_settings`, `openrag_update_settings`, `openrag_list_models`) use direct HTTP. Chat and search use the OpenRAG SDK (PyPI version is fine unless you need unreleased SDK changes).

### Run the MCP from source

```bash
cd sdks/mcp
uv sync
export OPENRAG_URL="http://localhost:3000"
export OPENRAG_API_KEY="orag_your_api_key"
uv run openrag-mcp
```

### Cursor: use repo path so it runs your code

In `~/.cursor/mcp.json`, set `--directory` to your **actual repo path** so Cursor runs the MCP from source:

```json
{
  "mcpServers": {
    "openrag": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/openrag/sdks/mcp",
        "openrag-mcp"
      ],
      "env": {
        "OPENRAG_URL": "https://your-openrag-instance.com",
        "OPENRAG_API_KEY": "orag_your_api_key_here"
      }
    }
  }
}
```

Replace `/path/to/openrag` with your real path (e.g. `/Users/edwin.jose/Documents/openrag`).

If you previously installed the MCP (`pip install openrag-mcp` or a wheel), uninstall it so Cursor uses the repo:

```bash
uv pip uninstall openrag-mcp
```

Then restart Cursor.

---

## Use cases and benefits

- **One integration, many apps** – Same MCP server works with Cursor, Claude Desktop, Watson Orchestrate, and any MCP client.
- **RAG in the loop** – Chat and search are grounded in your OpenRAG knowledge base, with optional filters and scoring.
- **Agent-friendly** – Agents can call OpenRAG for answers, list models, and read/update settings without custom APIs.
- **Lightweight** – No extra service to deploy; the host app spawns the server as a subprocess and talks over stdio.
- **Secure** – Only clients that have your `OPENRAG_API_KEY` (via env) can use the server to access OpenRAG.

**Example scenarios:** Query internal docs and runbooks from your IDE; power support bots with your product docs; search and summarize across ingested documents; automate workflows that need RAG (when document tools are enabled).

---


## Example prompts

Once the server is configured, you can ask the AI to:

- *"Search my knowledge base for authentication best practices"*
- *"Chat with OpenRAG about the Q4 roadmap"*
- *"What are the current OpenRAG settings?"*
- *"List available models for the openai provider"*
- *"Update OpenRAG to use chunk size 512"*

---

## Troubleshooting

### "OPENRAG_API_KEY environment variable is required"

Set `OPENRAG_API_KEY` in the `env` section of your MCP config (Cursor or Claude Desktop). The server reads it at startup.

### "Connection refused" or network errors

1. Confirm your OpenRAG instance is running and reachable.
2. Check `OPENRAG_URL` (no trailing slash; include `https://` if applicable).
3. Ensure no firewall or proxy is blocking the client machine from reaching OpenRAG.

### Tools not appearing

1. Restart the host app (Cursor or Claude Desktop) after changing the MCP config.
2. Check the app’s MCP/log output for errors (e.g. wrong `command`/`args` or missing `uv`/`uvx`).
3. If using "run from source", ensure `args` includes `--directory` and the correct path to `sdks/mcp`.

---

## License

Apache 2.0 - See [LICENSE](../../LICENSE) for details.
