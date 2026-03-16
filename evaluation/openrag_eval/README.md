# openrag-eval

OpenRAG Evaluation Tool - an evaluation framework for OpenRAG.

## Installation

### Prerequisites

Install [uv](https://docs.astral.sh/uv/) if you haven't already:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Development Installation with uv (Recommended)

```bash
cd openrag/evaluation/openrag_eval

# Create virtual environment
uv venv

# Install with development dependencies
uv sync --extra dev
```

**Note:** The `uv.lock` file is committed to the repository to ensure reproducible builds. When you run `uv sync`, it will use the exact versions specified in the lock file.

### Alternative: Using pip

```bash
cd openrag/evaluation/openrag_eval
pip install -e ".[dev]"
```

## Usage

```bash
# Run as a module
python -m openrag_eval
```

## Development

### Using uv (Recommended)

```bash
# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/openrag_eval --cov-report=term-missing

# Format code
uv run black src/ tests/

# Lint
uv run ruff check src/ tests/

# Type check
uv run mypy src/
```

### Using activated venv

```bash
# Activate the virtual environment
source .venv/bin/activate

# Then run commands directly
pytest
black src/ tests/
ruff check src/ tests/
mypy src/
```

## Structure

```
openrag_eval/
├── src/openrag_eval/    # Main package
└── tests/               # Tests