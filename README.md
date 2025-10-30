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

Use the OpenRAG Terminal User Interface (TUI) to manage your OpenRAG installation without complex command-line operations.

To quickly install and start OpenRAG, run `uvx openrag`.

To first set up a project and then install OpenRAG, do the following:

1. Create a new project with a virtual environment using `uv init`.

   ```bash
   uv init YOUR_PROJECT_NAME
   cd YOUR_PROJECT_NAME
   ```

   The `(venv)` prompt doesn't change, but `uv` commands will automatically use the project's virtual environment.
   For more information on virtual environments, see the [uv documentation](https://docs.astral.sh/uv/pip/environments).

2. Ensure all dependencies are installed and updated in your virtual environment.
   ```bash
   uv sync
   ```

3. Install and start the OpenRAG TUI.
   ```bash
   uvx openrag
   ```
   
   To install a specific version of the Langflow package, add the required version to the command, such as `uvx --from openrag==0.1.25 openrag`.

For the full TUI installation guide, see [TUI](https://docs.openr.ag/install).

## Docker or Podman installation

For more information, see [Install OpenRAG containers](https://docs.openr.ag/get-started/docker).

## Troubleshooting

For common issues and fixes, see [Troubleshoot](https://docs.openr.ag/support/troubleshoot).

## Development

For developers wanting to contribute to OpenRAG or set up a development environment, see [CONTRIBUTING.md](CONTRIBUTING.md).