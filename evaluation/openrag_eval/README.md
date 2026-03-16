# openrag-eval

OpenRAG Evaluation Tool - an evaluation framework for OpenRAG.

## Installation

### Development Installation

```bash
cd openrag/evaluation/openrag_eval
pip install -e .
```

### With Development Dependencies

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

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=src/openrag_eval --cov-report=term-missing

# Format code
black src/ tests/

# Lint
ruff check src/ tests/
```

## Structure

```
openrag_eval/
├── src/openrag_eval/    # Main package
└── tests/               # Tests