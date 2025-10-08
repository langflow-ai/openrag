<div align="center">

# OpenRAG

<div align="center">
  <a href="https://github.com/langflow-ai/langflow"><img src="https://img.shields.io/badge/Langflow-1C1C1E?style=flat&logo=langflow" alt="Langflow"></a>
  &nbsp;&nbsp;
  <a href="https://github.com/opensearch-project/OpenSearch"><img src="https://img.shields.io/badge/OpenSearch-005EB8?style=flat&logo=opensearch&logoColor=white" alt="OpenSearch"></a>
  &nbsp;&nbsp;
  <a href="https://github.com/encode/starlette"><img src="https://img.shields.io/badge/Starlette-009639?style=flat&logo=fastapi&logoColor=white" alt="Starlette"></a>
  &nbsp;&nbsp;
  <a href="https://github.com/vercel/next.js"><img src="https://img.shields.io/badge/Next.js-000000?style=flat&logo=next.js&logoColor=white" alt="Next.js"></a>
  &nbsp;&nbsp;
  <a href="https://deepwiki.com/phact/openrag"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>
</div>

OpenRAG is a comprehensive Retrieval-Augmented Generation platform that enables intelligent document search and AI-powered conversations. Users can upload, process, and query documents through a chat interface backed by large language models and semantic search capabilities. The system utilizes Langflow for document ingestion, retrieval workflows, and intelligent nudges, providing a seamless RAG experience. Built with Starlette, Next.js, OpenSearch, and Langflow integration.

</div>
<div align="center">
  <a href="#quickstart" style="color: #0366d6;">Quickstart</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#tui-interface" style="color: #0366d6;">TUI Interface</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#docker-deployment" style="color: #0366d6;">Docker Deployment</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#development" style="color: #0366d6;">Development</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#troubleshooting" style="color: #0366d6;">Troubleshooting</a>
</div>

## Quickstart

Use the OpenRAG Terminal User Interface (TUI) to manage your OpenRAG installation without complex command-line operations.

To launch OpenRAG with the TUI, do the following:

1. Clone the OpenRAG repository.
```bash
git clone https://github.com/langflow-ai/openrag.git
cd openrag
```

2. To start the TUI, from the repository root, run:
```bash
# Install dependencies first
uv sync

# Launch the TUI
uv run openrag
```

The TUI opens and guides you through OpenRAG setup.

For the full TUI guide, see [TUI](docs/docs/get-started/tui.mdx).

## Docker Deployment

If you prefer to use Docker to run OpenRAG, the repository includes two Docker Compose `.yml` files.
They deploy the same applications and containers, but to different environments.

- [`docker-compose.yml`](https://github.com/langflow-ai/openrag/blob/main/docker-compose.yml) is an OpenRAG deployment for environments with GPU support. GPU support requires an NVIDIA GPU with CUDA support and compatible NVIDIA drivers installed on the OpenRAG host machine. 

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

For more information, see [Deploy with Docker](docs/docs/get-started/docker.mdx).

## Troubleshooting

For common issues and fixes, see [Troubleshoot](docs/docs/support/troubleshoot.mdx).

## Development

For developers wanting to contribute to OpenRAG or set up a development environment, see [CONTRIBUTING.md](CONTRIBUTING.md).