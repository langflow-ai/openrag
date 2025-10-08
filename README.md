<div align="center">

# OpenRAG

</div>
<div align="center">
  <a href="#quick-start" style="color: #0366d6;">Quick Start</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#tui-interface" style="color: #0366d6;">TUI Interface</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#docker-deployment" style="color: #0366d6;">Docker Deployment</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#development" style="color: #0366d6;">Development</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#troubleshooting" style="color: #0366d6;">Troubleshooting</a>
</div>


OpenRAG is a comprehensive Retrieval-Augmented Generation platform that enables intelligent document search and AI-powered conversations. Users can upload, process, and query documents through a chat interface backed by large language models and semantic search capabilities. The system utilizes Langflow for document ingestion, retrieval workflows, and intelligent nudges, providing a seamless RAG experience. Built with Starlette, Next.js, OpenSearch, and Langflow integration. [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/phact/openrag)


<div align="center">
  <a href="https://github.com/langflow-ai/langflow"><img src="https://img.shields.io/badge/Langflow-1C1C1E?style=flat&logo=langflow" alt="Langflow"></a>
  &nbsp;&nbsp;
  <a href="https://github.com/opensearch-project/OpenSearch"><img src="https://img.shields.io/badge/OpenSearch-005EB8?style=flat&logo=opensearch&logoColor=white" alt="OpenSearch"></a>
  &nbsp;&nbsp;
  <a href="https://github.com/encode/starlette"><img src="https://img.shields.io/badge/Starlette-009639?style=flat&logo=fastapi&logoColor=white" alt="Starlette"></a>
  &nbsp;&nbsp;
  <a href="https://github.com/vercel/next.js"><img src="https://img.shields.io/badge/Next.js-000000?style=flat&logo=next.js&logoColor=white" alt="Next.js"></a>

</div>

## Quick Start

### Prerequisites

- Docker or Podman with Compose installed
- Make (for development commands)

### 1. Environment Setup

```bash
# Clone and setup environment
git clone https://github.com/langflow-ai/openrag.git
cd openrag
make setup  # Creates .env and installs dependencies
```

### 2. Configure Environment

Edit `.env` with your API keys and credentials:

```bash
# Required
OPENAI_API_KEY=your_openai_api_key
OPENSEARCH_PASSWORD=your_secure_password
LANGFLOW_SUPERUSER=admin
LANGFLOW_SUPERUSER_PASSWORD=your_secure_password
LANGFLOW_CHAT_FLOW_ID=your_chat_flow_id
LANGFLOW_INGEST_FLOW_ID=your_ingest_flow_id
NUDGES_FLOW_ID=your_nudges_flow_id
```
See extended configuration, including ingestion and optional variables: [docs/reference/configuration.mdx](docs/docs/reference/configuration.mdx)

### 3. Start OpenRAG

```bash
# Full stack with GPU support
make dev

# Or CPU only
make dev-cpu
```

Access the services:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **Langflow**: http://localhost:7860
- **OpenSearch**: http://localhost:9200
- **OpenSearch Dashboards**: http://localhost:5601

With OpenRAG started, ingest and retrieve documents with the [OpenRAG Quickstart](/docs/get-started/quickstart.mdx).

## TUI interface

OpenRAG includes a powerful Terminal User Interface (TUI) for easy setup, configuration, and monitoring. The TUI provides a user-friendly way to manage your OpenRAG installation without complex command-line operations.

![OpenRAG TUI Interface](assets/OpenRAG_TUI_2025-09-10T13_04_11_757637.svg)

### Launch OpenRAG with the TUI

From the repository root, run:

```bash
# Install dependencies first
uv sync

# Launch the TUI
uv run openrag
```

For the full TUI guide, see [docs/get-started/tui.mdx](docs/docs/get-started/tui.mdx)

## Docker Deployment

The repository includes two Docker Compose files.
They deploy the same applications and containers, but to different environments.

- [`docker-compose.yml`](https://github.com/langflow-ai/openrag/blob/main/docker-compose.yml) is an OpenRAG deployment with GPU support for accelerated AI processing.

- [`docker-compose-cpu.yml`](https://github.com/langflow-ai/openrag/blob/main/docker-compose-cpu.yml) is a CPU-only version of OpenRAG for systems without GPU support. Use this Docker compose file for environments where GPU drivers aren't available.

1. Clone the OpenRAG repository.
```bash
git clone https://github.com/langflow-ai/openrag.git
cd openrag
```

2. Build and start all services.

For the GPU-accelerated deployment, run:
```bash
docker compose build
docker compose up -d
```

For environments without GPU support, run: 
```bash
docker compose -f docker-compose-cpu.yml up -d
```

For more information, see [docs/get-started/docker.mdx](docs/docs/get-started/docker.mdx)

## Troubleshooting

For common issues and fixes, see [docs/support/troubleshoot.mdx](docs/docs/support/troubleshoot.mdx).

## Development

For developers wanting to contribute to OpenRAG or set up a development environment, please see our comprehensive development guide:

**[📚 See CONTRIBUTING.md for detailed development instructions](CONTRIBUTING.md)**

### Quick Development Commands

```bash
make help                    # See all available commands
make setup                   # Initial development setup
make infra                   # Start infrastructure services
make backend                 # Run backend locally
make frontend                # Run frontend locally
```