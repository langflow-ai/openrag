"""Installed as ``sitecustomize`` in the OpenRAG Langflow image (#2436).

Langflow builds a flow's components concurrently in worker threads, and the
OpenRAG LLM and Embeddings components both create ``openai.OpenAI`` clients.
The client imports its resource modules lazily on first attribute access
(``client.embeddings``, ``client.chat``, ...), and those modules import each
other (``resources.beta`` imports ``resources.chat``). When two threads hit
those first imports at once they take the per-module import locks in different
orders and Python raises ``_DeadlockError`` ("deadlock detected by
_ModuleLock('openai.resources.chat')"), failing the first flow run after
Langflow starts.

Importing ``openai.resources`` once at process startup, before any threads
exist, removes the race. Python imports ``sitecustomize`` automatically, so this
covers every way the image starts Langflow (the Dockerfile ``CMD`` and the Helm
``command:`` override). It only runs for ``langflow run`` so other Python
processes in the container don't pay the import cost.
"""

from __future__ import annotations

import os
import sys


def is_langflow_server(argv: list[str]) -> bool:
    """True for ``python -m langflow run ...`` or ``[.../]langflow run ...``."""
    return any(
        os.path.basename(arg) == "langflow" and argv[i + 1] == "run"
        for i, arg in enumerate(argv[:-1])
    )


def preload_openai_resources() -> None:
    try:
        import openai.resources  # noqa: F401
    except Exception as exc:  # never block Langflow from starting
        sys.stderr.write(f"Warning: could not preload openai.resources: {exc}\n")


if is_langflow_server(getattr(sys, "orig_argv", sys.argv)):
    preload_openai_resources()
