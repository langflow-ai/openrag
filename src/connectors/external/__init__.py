"""Generic adapter for connectors that live in the ``openrag_connectors`` package.

OpenRAG's ``ConnectionManager`` dispatches any registered external type
through :class:`ExternalConnector`, which is a single ``BaseConnector``
subclass that delegates to either a library-mode backend (in-process call
into ``openrag_connectors.<type>``) or a service-mode backend (HTTP client
to a stateless ``openrag-connectors`` service).

Until ``openrag-connectors`` is added to OpenRAG's dependencies, this
module supports a local-path fallback via the ``OPENRAG_CONNECTORS_PATH``
env var (default: ``../openrag-connectors/src`` relative to OpenRAG's repo
root). Remove it once the package is pinned in ``pyproject.toml``.
"""

import os
import sys
from pathlib import Path


def _ensure_package_importable() -> None:
    try:
        import openrag_connectors  # noqa: F401

        return
    except ImportError:
        pass

    candidate = os.environ.get("OPENRAG_CONNECTORS_PATH")
    if not candidate:
        repo_root = Path(__file__).resolve().parents[3]
        candidate = str(repo_root.parent / "openrag-connectors" / "src")
    if candidate and os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)


_ensure_package_importable()

from .shim import ExternalConnector

__all__ = ["ExternalConnector"]
