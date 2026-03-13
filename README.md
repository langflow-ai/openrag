<div align="center">

<img src="./docs/static/img/openrag-logo-dog.svg" alt="" width="120"/>

# OpenRAG

<h3>
  <em>Intelligent Agent-powered document search</em>
</h3>

<!-- Badges -->

[![Langflow](https://img.shields.io/badge/Langflow-1C1C1E?style=for-the-badge&logo=langflow)](https://github.com/langflow-ai/langflow)
[![OpenSearch](https://img.shields.io/badge/OpenSearch-005EB8?style=for-the-badge&logo=opensearch&logoColor=white)](https://github.com/opensearch-project/OpenSearch)
[![Docling](https://img.shields.io/badge/Docling-000000?style=for-the-badge)](https://github.com/docling-project/docling)

[![YouTube Channel](https://img.shields.io/youtube/channel/subscribers/UCn2bInQrjdDYKEEmbpwblLQ?label=Subscribe&style=social)](https://www.youtube.com/@OpenRAG/)
[![GitHub stars](https://img.shields.io/github/stars/langflow-ai/openrag?style=social)](https://github.com/langflow-ai/openrag/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/langflow-ai/openrag?style=social)](https://github.com/langflow-ai/openrag/network/members)

[![Documentation](https://img.shields.io/badge/Documentation-773eff)](https://docs.openr.ag) [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/langflow-ai/openrag)

</div>

---

OpenRAG is a comprehensive Retrieval-Augmented Generation platform that enables intelligent document search and AI-powered conversations.

Users can upload, process, and query documents through a chat interface backed by large language models and semantic search capabilities. The system utilizes Langflow for document ingestion, retrieval workflows, and intelligent nudges, providing a seamless RAG experience.

Check out the [documentation](https://docs.openr.ag/) or get started with the [quickstart](https://docs.openr.ag/quickstart).

Built with [FastAPI](https://fastapi.tiangolo.com/) and [Next.js](https://github.com/vercel/next.js). 
Powered by [OpenSearch](https://github.com/opensearch-project/OpenSearch), [Langflow](https://github.com/langflow-ai/langflow), and [Docling](https://github.com/docling-project/docling).

---

<div align="center">
  <img src="./docs/static/img/openrag_readme_downsized.gif" alt="OpenRAG Demo" width="100%"/>
</div>

## ✨ Highlight Features

- **Pre-packaged & ready to run** - All core tools are hooked up and ready to go, just install and run
- **Agentic RAG workflows** - Advanced orchestration with re-ranking and multi-agent coordination
- **Document ingestion** - Handles messy, real-world data with intelligent parsing
- **Drag-and-drop workflow builder** - Visual interface powered by Langflow for rapid iteration
- **Modular enterprise add-ons** - Extend functionality when you need it
- **Enterprise search at any scale** - Powered by OpenSearch for production-grade performance

## 🔄 How OpenRAG Works

OpenRAG follows a streamlined workflow to transform your documents into intelligent, searchable knowledge:

<div align="center">
  <img src="./docs/static/img/workflow-diagram.svg" alt="OpenRAG Workflow Diagram" width="800"/>
</div>

## 🚀 Install OpenRAG

To get started with OpenRAG, see the installation guides in the OpenRAG documentation:

* [Quickstart](https://docs.openr.ag/quickstart)
* [Install the OpenRAG Python package](https://docs.openr.ag/install-options)
* [Deploy self-managed services with Docker or Podman](https://docs.openr.ag/docker)

## ✨ Quick Start Workflow

<div align="center">

<img src="./docs/static/img/uv_run_openrag.png" alt="Use uv run openrag to start" width="300"/>

**1. Launch OpenRAG**

↓

<img src="./docs/static/img/add_knowledge_openrag.png" alt="Add files or folders as knowledge" width="300"/>

**2. Add Knowledge**

↓

<img src="./docs/static/img/chat_openrag.png" alt="Start Chatting with your knowledge" width="700"/>

**3. Start Chatting**

</div>

## 📦 SDKs

Integrate OpenRAG into your applications with our official SDKs:

### Python SDK
```bash
pip install openrag-sdk
```

**Quick Example:**
```python
import asyncio
from openrag_sdk import OpenRAGClient


async def main():
    async with OpenRAGClient() as client:
        response = await client.chat.create(message="What is RAG?")
        print(response.response)


if __name__ == "__main__":
    asyncio.run(main())
```

📖 [Full Python SDK Documentation](https://pypi.org/project/openrag-sdk/)

### TypeScript/JavaScript SDK
```bash
npm install openrag-sdk
```

**Quick Example:**
```typescript
import { OpenRAGClient } from "openrag-sdk";

const client = new OpenRAGClient();
const response = await client.chat.create({ message: "What is RAG?" });
console.log(response.response);
```

📖 [Full TypeScript/JavaScript SDK Documentation](https://www.npmjs.com/package/openrag-sdk)

## 🔌 Model Context Protocol (MCP)

Connect AI assistants like Cursor and Claude Desktop to your OpenRAG knowledge base:

```bash
pip install openrag-mcp
```

**Quick Example (Cursor/Claude Desktop config):**
```json
{
  "mcpServers": {
    "openrag": {
      "command": "uvx",
      "args": ["openrag-mcp"],
      "env": {
        "OPENRAG_URL": "http://localhost:3000",
        "OPENRAG_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

The MCP server provides tools for RAG-enhanced chat, semantic search, and settings management.

📖 [Full MCP Documentation](https://pypi.org/project/openrag-mcp/)

## 🛠️ Development

For developers who want to [contribute to OpenRAG](https://docs.openr.ag/support/contribute) or set up a development environment, see [CONTRIBUTING.md](CONTRIBUTING.md).

## 🛟 Troubleshooting

For assistance with OpenRAG, see [Troubleshoot OpenRAG](https://docs.openr.ag/support/troubleshoot) and visit the [Discussions page](https://github.com/langflow-ai/openrag/discussions).

To report a bug or submit a feature request, visit the [Issues page](https://github.com/langflow-ai/openrag/issues).