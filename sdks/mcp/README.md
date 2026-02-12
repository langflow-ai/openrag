# OpenRAG MCP Server

An MCP (Model Context Protocol) server that exposes OpenRAG capabilities to AI assistants like Claude Desktop and Cursor.

## Features

- **Chat** - RAG-enhanced conversations with your knowledge base
- **Search** - Semantic search over your documents
- **Document Management** - Ingest files/URLs and manage your knowledge base

## Available Tools

| Tool | Description |
|:-----|:------------|
| `openrag_chat` | Send a message and get a RAG-enhanced response |
| `openrag_search` | Semantic search over the knowledge base |
| `openrag_ingest_file` | Ingest a local file into the knowledge base |
| `openrag_ingest_url` | Ingest content from a URL |
| `openrag_list_documents` | List documents in the knowledge base |
| `openrag_delete_document` | Delete a document from the knowledge base |

## Prerequisites

1. A running OpenRAG instance
2. An OpenRAG API key (create one in Settings → API Keys)
3. Python 3.10+ with `uv` installed

## Build and run locally

To use the **latest MCP code** (including settings and models tools), run from source. Do **not** install the MCP package if you want local edits to apply.

### What to build (in order)

| Step | What | Command | Required for |
|------|------|---------|--------------|
| 1 | OpenRAG backend | Run your OpenRAG app (e.g. frontend + API) | All tools |
| 2 | MCP from source | `cd sdks/mcp && uv sync` | All tools; no wheel needed |
| 3 | (Optional) SDK from repo | `cd sdks/python && uv pip install -e .` | Only for latest chat/search/documents SDK |

**Settings and models tools** (`openrag_get_settings`, `openrag_update_settings`, `openrag_list_models`) use direct HTTP and do **not** require the SDK. Chat, search, and document tools use the SDK (PyPI version is fine unless you need unreleased SDK changes).

### Run the MCP from source

```bash
cd sdks/mcp
uv sync
export OPENRAG_URL="http://localhost:3000"
export OPENRAG_API_KEY="orag_your_api_key"
uv run openrag-mcp
```

### Cursor: use repo path so it runs your code

In `~/.cursor/mcp.json`, set `--directory` to your **actual repo path** so Cursor runs the MCP from source, not an installed package:

```json
"args": ["run", "--directory", "/Users/edwin.jose/Documents/openrag/sdks/mcp", "openrag-mcp"]
```

If you previously installed the MCP (`pip install openrag-mcp` or installed a wheel), **uninstall it** so Cursor uses the repo:

```bash
uv pip uninstall openrag-mcp
```

Then restart Cursor.

## Installation

### Option 1: Run from Source (Recommended for Development)

```bash
cd openrag/sdks/mcp
uv sync
```

Use `uv run openrag-mcp` from that directory, or point Cursor/Claude `--directory` to this path.

### Option 2: Install from GitHub

```bash
pip install "openrag-mcp @ git+https://github.com/your-org/openrag.git#subdirectory=sdks/mcp"
```

## Configuration

The MCP server requires two environment variables:

| Variable | Description | Default |
|:---------|:------------|:--------|
| `OPENRAG_URL` | URL of your OpenRAG instance | `http://localhost:3000` |
| `OPENRAG_API_KEY` | Your OpenRAG API key | (required) |

## Usage with Claude Desktop

Add this to your Claude Desktop configuration file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

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

**Important:** Replace `/path/to/openrag` with the actual path to your OpenRAG repository.

## Usage with Cursor

Add this to your Cursor MCP configuration:

**Location:** `~/.cursor/mcp.json`

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

## Testing

You can test the MCP server locally:

```bash
cd /path/to/openrag/sdks/mcp

# Set environment variables
export OPENRAG_URL="http://localhost:3000"
export OPENRAG_API_KEY="orag_your_test_key"

# Run the server (it will wait for MCP protocol input)
uv run openrag-mcp
```

## Example Prompts

Once configured, you can ask Claude or Cursor things like:

- *"Search my knowledge base for information about machine learning"*
- *"What documents do I have in OpenRAG?"*
- *"Chat with OpenRAG about the quarterly report"*
- *"Ingest this PDF: /path/to/document.pdf"*
- *"Delete the file 'old_report.pdf' from my knowledge base"*

## Troubleshooting

### "OPENRAG_API_KEY environment variable is required"

Make sure you've set the `OPENRAG_API_KEY` in the `env` section of your MCP configuration.

### "Connection refused" errors

1. Check that your OpenRAG instance is running
2. Verify the `OPENRAG_URL` is correct
3. Ensure there are no firewall rules blocking the connection

### Tools not appearing in Claude Desktop

1. Restart Claude Desktop after updating the configuration
2. Check the Claude Desktop logs for error messages
3. Verify the path to the `openrag/sdks/mcp` directory is correct

## Architecture

```
┌─────────────────┐      stdio        ┌─────────────────┐       HTTPS        ┌─────────────────┐
│  Claude Desktop │◄─────────────────►│  openrag-mcp    │◄──────────────────►│    OpenRAG      │
│    or Cursor    │   JSON-RPC (MCP)  │  (subprocess)   │   X-API-Key auth   │   deployment    │
└─────────────────┘                   └─────────────────┘                    └─────────────────┘
```

## License

Apache 2.0 - See [LICENSE](../../LICENSE) for details.

