<div align="center">

# OpenRAG

<div align="center">
  <a href="https://github.com/langflow-ai/langflow"><img src="https://img.shields.io/badge/Langflow-1C1C1E?style=flat&logo=langflow" alt="Langflow"></a>
  &nbsp;&nbsp;
  <a href="https://github.com/opensearch-project/OpenSearch"><img src="https://img.shields.io/badge/OpenSearch-005EB8?style=flat&logo=opensearch&logoColor=white" alt="OpenSearch"></a>
  &nbsp;&nbsp;
  <a href="https://github.com/docling-project/docling"><img src="https://img.shields.io/badge/Docling-000000?style=flat" alt="Langflow"></a>
  &nbsp;&nbsp;
</div>

OpenRAG is a comprehensive Retrieval-Augmented Generation platform that enables intelligent document search and AI-powered conversations. Users can upload, process, and query documents through a chat interface backed by large language models and semantic search capabilities. The system utilizes Langflow for document ingestion, retrieval workflows, and intelligent nudges, providing a seamless RAG experience. Built with [Starlette](https://github.com/Kludex/starlette) and [Next.js](https://github.com/vercel/next.js). Powered by [OpenSearch](https://github.com/opensearch-project/OpenSearch), [Langflow](https://github.com/langflow-ai/langflow), and [Docling](https://github.com/docling-project/docling).

<a href="https://deepwiki.com/langflow-ai/openrag"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>

</div>
<div align="center">
  <a href="#quickstart" style="color: #0366d6;">Quickstart</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#tui-interface" style="color: #0366d6;">TUI Interface</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#docker-deployment" style="color: #0366d6;">Docker Deployment</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#development" style="color: #0366d6;">Development</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#troubleshooting" style="color: #0366d6;">Troubleshooting</a>
</div>

## Quickstart

To quickly run OpenRAG without creating or modifying any project files, use the automatic installer script.

The script detects and installs uv, Docker/Podman, and Docker Compose prerequisites, then runs OpenRAG with `uvx`.

> **Note:** When the script runs `uvx openrag`, `uv` automatically downloads and installs Python 3.10-3.13 if it's not already on your system. You don't need Python pre-installed when using the automatic installer, but having it pre-installed is recommended for better reliability.

1. Create a directory to store the OpenRAG configuration files:

    ```bash
    mkdir openrag-workspace
    cd openrag-workspace
   ```

2. Run the installer:

    ```bash
    curl -fsSL https://docs.openr.ag/files/run_openrag_with_prereqs.sh | bash
    ```

    The OpenRAG Terminal User Interface (TUI) starts and guides you through setup.

3. Continue with the [Quickstart](https://docs.openr.ag/quickstart).

## Install Python package

To first set up a project and then install the OpenRAG Python package, do the following:

1. Create a new project with a virtual environment using `uv init`.

   ```bash
   uv init YOUR_PROJECT_NAME
   cd YOUR_PROJECT_NAME
   ```

   The `(venv)` prompt doesn't change, but `uv` commands will automatically use the project's virtual environment.
   For more information on virtual environments, see the [uv documentation](https://docs.astral.sh/uv/pip/environments).

2. Add OpenRAG to your project.
   ```bash
   uv add openrag
   ```

   To add a specific version of OpenRAG:
   ```bash
   uv add openrag==0.1.25
   ```

3. Start the OpenRAG TUI.
   ```bash
   uv run openrag
   ```

4. Continue with the [Quickstart](https://docs.openr.ag/quickstart).

For the full TUI installation guide, see [TUI](https://docs.openr.ag/install).

## Docker or Podman installation

For more information, see [Install OpenRAG containers](https://docs.openr.ag/docker).

## Troubleshooting

For common issues and fixes, see [Troubleshoot](https://docs.openr.ag/support/troubleshoot).

## Development

For developers wanting to contribute to OpenRAG or set up a development environment, see [CONTRIBUTING.md](CONTRIBUTING.md).