"""OpenRAG backend entry point.

Most of what used to live in this file moved into focused modules:
- app/factory.py                       — FastAPI app construction
- app/container.py                     — service DI container
- app/lifespan.py                      — startup + shutdown lifecycle
- app/middleware.py                    — request logging
- app/routes/                          — route registrars (internal, public_v1, mcp)
- services/default_docs_service.py     — bundled-docs onboarding/refresh
- services/startup_orchestrator.py     — per-startup tasks (OpenSearch, flows, MCP URLs)
- utils/opensearch_init.py             — OpenSearch index/security setup
- utils/jwt_keygen.py                  — RSA keypair generation
- utils/url_content_fetcher.py         — URL → text-file helper
- api/health.py                        — liveness + readiness probes

This module is intentionally thin: import bootstrap, run Alembic, build
the app, run uvicorn. The re-exports below preserve the
`from main import …` contract used by tests and api/settings.py.
"""

import bootstrap  # noqa: F401  — must be first; loads .env + structured logging

import asyncio
import atexit

# Re-exported so tests that monkeypatch "main.httpx.AsyncClient" keep working.
# Module attributes in Python are shared singletons, so the patch propagates
# to services/default_docs_service.py which calls httpx.AsyncClient directly.
import httpx  # noqa: F401

from app.factory import create_app
from config.settings import ACCESS_LOG_ENABLED
from services.default_docs_service import (
    _get_remote_docs_signature,
    _should_use_url_default_docs_ingest,
    ingest_default_documents_when_ready,
    refresh_default_openrag_docs,
)
from services.startup_orchestrator import startup_tasks
from utils.encryption import enforce_startup_prerequisites
from utils.jwt_keygen import generate_jwt_keys
from utils.logging_config import get_logger
from utils.opensearch_init import _ensure_opensearch_index, init_index

enforce_startup_prerequisites()
logger = get_logger(__name__)

__all__ = [
    "create_app",
    "startup_tasks",
    "generate_jwt_keys",
    "init_index",
    "_ensure_opensearch_index",
    "ingest_default_documents_when_ready",
    "refresh_default_openrag_docs",
    "_get_remote_docs_signature",
    "_should_use_url_default_docs_ingest",
]


def cleanup():
    """Cleanup on application shutdown (atexit hook)."""
    logger.info("Application shutting down")


if __name__ == "__main__":
    import uvicorn

    atexit.register(cleanup)

    # Run Alembic upgrade SYNCHRONOUSLY before the app builds. This
    # avoids two pitfalls:
    #   1. Alembic's env.py uses asyncio.run() which collides with a
    #      live event loop.
    #   2. Anything done inside `asyncio.run(create_app())` binds to a
    #      loop that is closed before uvicorn starts — including DB
    #      engines. Putting the schema migration here keeps the runtime
    #      `init_engine()` deferred to the lifespan startup, on the
    #      live uvicorn loop.
    try:
        from db.migrations_runtime import run_alembic_upgrade

        run_alembic_upgrade("head")
    except Exception as _e:
        logger.error("Alembic upgrade failed at startup", error=str(_e))
        raise

    app = asyncio.run(create_app())

    uvicorn.run(
        app,
        workers=1,
        host="0.0.0.0",
        port=8000,
        reload=False,
        access_log=ACCESS_LOG_ENABLED,
        log_config=None,
    )
