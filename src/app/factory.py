"""FastAPI application factory.

Wires the service container, middleware, routes, and lifespan together
into a ready-to-serve FastAPI app.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.container import initialize_services
from app.lifespan import run_shutdown, run_startup
from app.middleware import RequestLoggingMiddleware
from app.routes import register_all_routes
from config.settings import CORS_ALLOWED_ORIGINS, FASTAPI_DEBUG
from utils.logging_config import get_logger
from utils.version_utils import BOMARAG_VERSION

logger = get_logger(__name__)


async def create_app():
    """Create and configure the FastAPI application"""
    services = await initialize_services()

    app = FastAPI(title="BomaRAG API", version=BOMARAG_VERSION, debug=FASTAPI_DEBUG)
    app.state.services = services
    app.state.background_tasks = set()

    if CORS_ALLOWED_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=CORS_ALLOWED_ORIGINS,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

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

    # Wire startup/shutdown via on_event handlers (not lifespan=). FastAPI
    # runs these through the ASGI lifespan; integration tests drive the same
    # path by entering/exiting app.router.lifespan_context(app) directly,
    # since Starlette 1.x removed the Router.startup()/shutdown() helpers.
    @app.on_event("startup")
    async def _startup():
        await run_startup(app)

    @app.on_event("shutdown")
    async def _shutdown():
        await run_shutdown(app)

    return app
