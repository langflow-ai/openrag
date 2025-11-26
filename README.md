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
  <a href="#install-python-package" style="color: #0366d6;">Python package</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#docker-or-podman-installation" style="color: #0366d6;">Docker or Podman</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#development" style="color: #0366d6;">Development</a> &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#troubleshooting" style="color: #0366d6;">Troubleshooting</a>
</div>

## Quickstart

To run OpenRAG without creating or modifying any project files, use `uvx`:

```bash
uvx openrag
```

This command runs OpenRAG without installing it to your project or globally.

To run a specific version of OpenRAG, run `uvx --from openrag==VERSION openrag`.

## Install Python package

To add the OpenRAG Python package to a Python project, use `uv`:

1. Create a new project with a virtual environment using `uv init`:

   ```bash
   uv init YOUR_PROJECT_NAME
   cd YOUR_PROJECT_NAME
   ```

   The `(venv)` prompt doesn't change, but `uv` commands will automatically use the project's virtual environment.
   For more information on virtual environments, see the [uv documentation](https://docs.astral.sh/uv/pip/environments).

2. Add OpenRAG to your project:

   ```bash
   uv add openrag
   ```

   To add a specific version of OpenRAG, run `uv add openrag==VERSION`.

3. Start the OpenRAG terminal user interface (TUI):

   ```bash
   uv run openrag
   ```

4. Continue with the [Quickstart](https://docs.openr.ag/quickstart).

For all installation options, see the [OpenRAG installation guide](https://docs.openr.ag/install).

## Docker or Podman installation

By default, OpenRAG automatically starts the required containers and helps you manage them.
To install OpenRAG with self-managed containers, see the [OpenRAG installation guide](https://docs.openr.ag/docker).

## Development

For developers wanting to contribute to OpenRAG or set up a development environment, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Troubleshooting

For common issues and fixes, see [Troubleshoot OpenRAG](https://docs.openr.ag/support/troubleshoot).