# BomaRAG MCP

> **The Python package `bomarag-mcp` is deprecated and no longer updated. Use the built-in streamable HTTP endpoint instead.**

BomaRAG ships a built-in [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server over **streamable HTTP**, mounted on your BomaRAG instance at `/mcp`. This endpoint is part of your BomaRAG deployment; when connecting locally, nothing leaves your network.

Any MCP client that supports URL-based server configs, such as [Cursor](https://docs.cursor.com/context/model-context-protocol), [Claude Desktop](https://modelcontextprotocol.io/quickstart/user), and the MCP SDK, can connect directly to this endpoint.

There is no subprocess to spawn and nothing extra to install. Your client connects over HTTP using the same BomaRAG API key you use for the REST API. Document ingestion, task tracking, and knowledge filter tools are available directly.

## Prerequisites

In addition to a running BomaRAG instance, you need an BomaRAG API key and your BomaRAG MCP endpoint URL.

### Authentication

You need an BomaRAG API key (prefixed by `orag_`). You can create an BomaRAG API key in **Settings → API Keys**.

Pass your BomaRAG API key on every request using the `X-API-Key` or `Authorization: Bearer` headers.

The same key works for both the REST API and MCP, and it is forwarded transparently to the underlying endpoints.

### Endpoint URL

The MCP endpoint is `/mcp` on your BomaRAG instance. The host and port depend on how BomaRAG is deployed:

| Deployment | MCP URL |
|:-----------|:--------|
| Default Docker deployment | `http://localhost:3000/mcp` |
| Backend run directly (dev, outside Docker) | `http://localhost:8000/mcp` |
| Remote / deployed instance | `https://your-bomarag-instance.com/mcp` |

In the default Docker deployment the backend port (`8000`) is not published to the host. The BomaRAG frontend on port `3000` proxies `/mcp` to the backend and forwards your authentication headers. Therefore, **`http://localhost:3000/mcp`** is the correct local URL for a standard install.

Use `http://localhost:8000/mcp` only when you run the backend directly without the frontend.

The following examples use the local Docker URL; replace this URL with your own host if you need to connect to a remote instance.

## Cursor

Config file: `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "bomarag": {
      "url": "http://localhost:3000/mcp",
      "headers": {
        "X-API-Key": "orag_your_api_key_here"
      }
    }
  }
}
```

Restart Cursor after saving the config file.

## Claude Desktop

Config file:

* macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
* Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "bomarag": {
      "url": "http://localhost:3000/mcp",
      "headers": {
        "X-API-Key": "orag_your_api_key_here"
      }
    }
  }
}
```

Restart Claude Desktop after editing the config file.

## IBM Bob

Add the server to your IBM Bob MCP config with `type` set to `streamable-http`:

```json
{
  "mcpServers": {
    "bomarag": {
      "type": "streamable-http",
      "url": "http://localhost:3000/mcp",
      "headers": {
        "x-api-key": "orag_your_api_key_here"
      }
    }
  }
}
```

For more information, see [MCP integration with IBM Bob](https://www.ibm.com/think/tutorials/mcp-integration-ibm-bob).

## Available tools

All tools are auto-exposed from the `/v1/` API, and they are available immediately after connecting:

| Tool | Description |
| ---- | ----------- |
| `bomarag_chat` | Send a message and get a RAG-enhanced response. Supports `chat_id` and `filter_id`. |
| `bomarag_list_chats` | List all chat conversations. |
| `bomarag_get_chat` | Get a specific chat conversation by ID. |
| `bomarag_delete_chat` | Delete a chat conversation by ID. |
| `bomarag_search` | Semantic search over the knowledge base. Supports filters, score threshold, data sources. |
| `bomarag_ingest` | Ingest documents (files, URLs, text) into the knowledge base. Returns a `task_id`. |
| `bomarag_get_task_status` | Check the status of an ingestion task by `task_id`. |
| `bomarag_delete_document` | Delete a document from the knowledge base by filename. |
| `bomarag_get_settings` | Get current BomaRAG configuration (LLM, embeddings, chunk settings, system prompt). |
| `bomarag_update_settings` | Update BomaRAG configuration. All fields are optional. |
| `bomarag_list_models` | List available models for a provider (`openai`, `anthropic`, `ollama`, `watsonx`). |
| `bomarag_create_knowledge_filter` | Create a knowledge filter to scope searches and chats. |
| `bomarag_search_knowledge_filters` | Search knowledge filters by name or criteria. |
| `bomarag_get_knowledge_filter` | Get a knowledge filter by ID. |
| `bomarag_update_knowledge_filter` | Update an existing knowledge filter. |
| `bomarag_delete_knowledge_filter` | Delete a knowledge filter by ID. |

## License

Apache 2.0 — see [LICENSE](../../LICENSE) for details.