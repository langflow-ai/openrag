# OpenRAG MCP — Final Release Notice

> **This package (`openrag-mcp`) has been retired.**
>
> OpenRAG now ships a built-in [Model Context Protocol](https://modelcontextprotocol.io/) server over **streamable HTTP** — no subprocess, no separate install, no API key in a subprocess env block. Connect your MCP client directly to your running OpenRAG instance.
>
> The last published version of `openrag-mcp` on PyPI is the final release. No further updates will be made to this package.

---

## Migrating to streamable HTTP

The OpenRAG backend exposes an MCP endpoint at `/mcp` using the streamable-HTTP transport. Any MCP client that supports `"url"`-based server configs (Cursor, Claude Desktop, and the MCP SDK) can connect to it directly.

### Prerequisites

- A running OpenRAG instance (v0.3.0 or later)
- An OpenRAG API key — create one in **Settings → API Keys**

---

## Cursor

**Config file:** `~/.cursor/mcp.json`

**Standard API key:**

```json
{
  "mcpServers": {
    "openrag": {
      "url": "https://your-openrag-instance.com/mcp",
      "headers": {
        "X-API-Key": "orag_your_api_key_here"
      }
    }
  }
}
```

**IBM auth (when `IBM_AUTH_ENABLED=true` on the server):**

```json
{
  "mcpServers": {
    "openrag": {
      "url": "https://your-openrag-instance.com/mcp",
      "headers": {
        "X-Username": "your_ibm_username",
        "X-Api-Key": "your_ibm_api_key"
      }
    }
  }
}
```

Restart Cursor after saving the config.

---

## Claude Desktop

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

**Standard API key:**

```json
{
  "mcpServers": {
    "openrag": {
      "url": "https://your-openrag-instance.com/mcp",
      "headers": {
        "X-API-Key": "orag_your_api_key_here"
      }
    }
  }
}
```

**IBM auth:**

```json
{
  "mcpServers": {
    "openrag": {
      "url": "https://your-openrag-instance.com/mcp",
      "headers": {
        "X-Username": "your_ibm_username",
        "X-Api-Key": "your_ibm_api_key"
      }
    }
  }
}
```

Restart Claude Desktop after editing the file.

---

## Available tools

All tools are auto-exposed from the `/v1/` API and are available immediately after connecting:

| Tool | Description |
|:-----|:------------|
| `openrag_chat` | Send a message and get a RAG-enhanced response. Supports `chat_id` and `filter_id`. |
| `openrag_list_chats` | List all chat conversations. |
| `openrag_get_chat` | Get a specific chat conversation by ID. |
| `openrag_delete_chat` | Delete a chat conversation by ID. |
| `openrag_search` | Semantic search over the knowledge base. Supports filters, score threshold, data sources. |
| `openrag_ingest` | Ingest documents (files, URLs, text) into the knowledge base. Returns a `task_id`. |
| `openrag_get_task_status` | Check the status of an ingestion task by `task_id`. |
| `openrag_delete_document` | Delete a document from the knowledge base by filename. |
| `openrag_get_settings` | Get current OpenRAG configuration (LLM, embeddings, chunk settings, system prompt). |
| `openrag_update_settings` | Update OpenRAG configuration. All fields are optional. |
| `openrag_list_models` | List available models for a provider (`openai`, `anthropic`, `ollama`, `watsonx`). |
| `openrag_create_knowledge_filter` | Create a knowledge filter to scope searches and chats. |
| `openrag_search_knowledge_filters` | Search knowledge filters by name or criteria. |
| `openrag_get_knowledge_filter` | Get a knowledge filter by ID. |
| `openrag_update_knowledge_filter` | Update an existing knowledge filter. |
| `openrag_delete_knowledge_filter` | Delete a knowledge filter by ID. |

---

## Why streamable HTTP?

- **No subprocess** — your MCP client connects over HTTP; nothing to install or spawn locally.
- **Full tool surface** — document ingestion, task tracking, and knowledge filters are available from day one (previously listed as "coming later" in the stdio package).
- **One auth model** — the same API key or IBM credentials you use for the REST API work for MCP.
- **Self-hosted and secure** — the `/mcp` endpoint is part of your OpenRAG deployment; nothing leaves your network.

---

## License

Apache 2.0 — see [LICENSE](../../LICENSE) for details.
