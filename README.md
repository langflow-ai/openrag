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

Both Docker deployments depend on `docling serve` to be running on port `5001` on the host machine. This is required to take advantage of[Mac MLX](https://opensource.apple.com/projects/mlx/) support for document processing. Installing OpenRAG with the TUI starts `docling serve` automatically, but for a Docker deployment you must manually start the `docling serve` process.

Alternatively, set `DISABLE_INGEST_WITH_LANGFLOW=true` in your `.env` to use OpenRAG's built-in pipeline, which uses docling directly without requiring `docling serve`.

To deploy OpenRAG with Docker:

1. Clone the OpenRAG repository.
    ```bash
    git clone https://github.com/langflow-ai/openrag.git
    cd openrag
    ```

2. Install dependencies.
    ```bash
    uv sync
    ```

3. Start `docling serve` on the host machine.
    ```bash
    uv run python scripts/docling_ctl.py start --port 5001
    ```
    
4. Confirm `docling serve` is running.
    ```
    uv run python scripts/docling_ctl.py status
    ```

    Successful result:
    ```bash
    Status: running
    Endpoint: http://127.0.0.1:5001
    Docs: http://127.0.0.1:5001/docs
    PID: 27746
    ```

5. Build and start all services.

    For the GPU-accelerated deployment, run:
    ```bash
    docker compose build
    docker compose up -d
    ```

    For environments without GPU support, run: 
    ```bash
    docker compose -f docker-compose-cpu.yml up -d
    ```

   The OpenRAG Docker Compose file starts five containers:
   | Container Name | Default Address | Purpose |
   |---|---|---|
   | OpenRAG Backend | http://localhost:8000 | FastAPI server and core functionality. |
   | OpenRAG Frontend | http://localhost:3000 | React web interface for users. |
   | Langflow | http://localhost:7860 | AI workflow engine and flow management. |
   | OpenSearch | http://localhost:9200 | Vector database for document storage. |
   | OpenSearch Dashboards | http://localhost:5601 | Database administration interface. |

    You can now access the OpenRAG application at `http://localhost:3000`.

    To stop `docling serve`, run:

    ```bash
    uv run python scripts/docling_ctl.py stop
    ```

For more information, see [Deploy with Docker](docs/docs/get-started/docker.mdx).

## Troubleshooting

For common issues and fixes, see [Troubleshoot](docs/docs/support/troubleshoot.mdx).

## Development

For developers wanting to contribute to OpenRAG or set up a development environment, see [CONTRIBUTING.md](CONTRIBUTING.md).