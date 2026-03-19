# openrag-workbench

OpenRAG Workbench Tool - an evaluation framework for OpenRAG.

## Installation

### Prerequisites

Install [uv](https://docs.astral.sh/uv/):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Installation

```bash
cd openrag/evaluation/openrag_workbench

# Create virtual environment
uv venv

# Install with dependencies
uv sync
```

## Usage

Run the main evaluation script:

```bash
uv run python -m openrag_workbench.evaluate
```


## Development

For development, install with development dependencies:

```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests with uv
uv run pytest

# Format code with uv
uv run black src/ tests/

# Lint code with uv
uv run ruff check src/ tests/

# Type check with uv
uv run mypy src/
```

## Structure

The project is organized as follows:

```
openrag_workbench/
├── src/openrag_workbench/    # Main package
│   ├── pipelines/       # Ingest and inference pipelines
│   ├── boards/          # Evaluation board configurations
│   └── evaluate.py      # Main evaluation script
└── tests/               # Tests
```

The main components are:

### Pipelines (`src/openrag_workbench/pipelines/`)
Contains implementations of RAG pipelines:
- **`ingest.py`**: A RagWorkbench ingestion pipeline implemented with the OpenRAG SDK
- **`inference.py`**: A RagWorkbench inference pipeline implemented with the OpenRAG SDK

### Boards (`src/openrag_workbench/boards/`)
Contains board configurations for evaluation experiments:
- **`table_rich/`**: A definition for RAG experiments over table-rich documents.

