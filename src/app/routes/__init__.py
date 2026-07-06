"""Route registration entry point.

The factory calls `register_all_routes(app)`. Each sub-module
owns one cohesive group of endpoints.
"""

from fastapi import FastAPI

from app.routes.internal import register_internal_routes
from app.routes.mcp import mount_mcp
from app.routes.public_v1 import register_public_v1_routes


def register_all_routes(app: FastAPI):
    """Wire every HTTP/MCP route onto the FastAPI app.

    Returns the MCP http_app's lifespan context manager (or None) so the
    application lifespan can enter/exit it at the right time.
    """
    register_internal_routes(app)
    register_public_v1_routes(app)
    mcp_lifespan_ctx = mount_mcp(app)
    return mcp_lifespan_ctx
