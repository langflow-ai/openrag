"""FastAPI application factory.

Wires the service container, middleware, routes, and lifespan together
into a ready-to-serve FastAPI app.
"""

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.container import initialize_services
from app.lifespan import run_shutdown, run_startup
from app.middleware import RequestLoggingMiddleware
from app.routes import register_all_routes
from config.settings import FASTAPI_DEBUG
from utils.logging_config import get_logger
from utils.version_utils import OPENRAG_VERSION

logger = get_logger(__name__)


async def create_app():
    """Create and configure the FastAPI application"""
    services = await initialize_services()

    app = FastAPI(title="OpenRAG API", version=OPENRAG_VERSION, debug=FASTAPI_DEBUG)
    app.state.services = services
    app.state.background_tasks = set()

    # Wire up ASGI request logging middleware (pure ASGI, not BaseHTTPMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    try:
        Instrumentator().instrument(app).expose(app)
    except Exception as e:
        logger.error(f"Failed to instrument app with Prometheus: {str(e)}")

    # Register all route handlers and mount the MCP server. The MCP
    # http_app's lifespan context manager is stored on app.state so the
    # application lifespan can enter/exit it at the right time.
    mcp_lifespan_ctx = register_all_routes(app)
    app.state.mcp_lifespan_ctx = mcp_lifespan_ctx

    # Wire startup/shutdown via on_event handlers (not lifespan=) so that
    # `app.router.startup()` / `app.router.shutdown()` triggers them — the
    # integration tests rely on this contract.
    @app.on_event("startup")
    async def _startup():
        await run_startup(app)

    @app.on_event("shutdown")
    async def _shutdown():
        await run_shutdown(app)

    return app
