# openrag

npm bootstrap for [OpenRAG](https://github.com/langflow-ai/openrag) — Intelligent Agent-powered document search and RAG platform.

> **Note:** OpenRAG is a Python application. This npm package exists solely as a convenience installer and launcher — it does not contain any application code itself. Under the hood, it installs the Python `openrag` package and delegates all commands to the Python CLI.

## Install

```bash
npm install -g openrag
```

This will:
1. Check that Python >= 3.13 is available on your system
2. Install the Python `openrag` package using the best available tool (`uv` > `pipx` > `pip`)
3. Register the `openrag` command globally via npm so you can run it from anywhere

## Requirements

- **Node.js** >= 16 (for the npm installer only)
- **Python** >= 3.13 (required — this is what actually runs OpenRAG)

## Usage

```bash
openrag
```

Run the setup walkthrough to bootstrap your OpenRAG instance, or use `openrag --tui` for the full terminal UI.

## Why an npm package for a Python app?

npm provides a familiar, cross-platform `install -g` experience. This package handles the Python dependency installation for you so you don't need to worry about `pip`, `pipx`, or `uv` yourself. If you prefer to install directly via Python, you can skip this entirely:

```bash
pip install openrag
# or
uv tool install openrag
```
