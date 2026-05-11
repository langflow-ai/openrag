"""FastMCP streamable-HTTP server mounted at /mcp.

Returns the MCP http_app's lifespan context manager so the application
lifespan can enter/exit it inline (FastAPI does not propagate lifespan
to mounted sub-apps automatically).
"""

from fastapi import FastAPI

from mcp_http.server import create_mcp_server
from utils.logging_config import get_logger

logger = get_logger(__name__)


def mount_mcp(app: FastAPI):
    """Mount the FastMCP app at /mcp and return its lifespan context manager."""
    logger.info("Creating MCP server")
    mcp_server = create_mcp_server(app)
    mcp_http_app = mcp_server.http_app(transport="streamable-http", path="/")
    app.mount("/mcp", mcp_http_app)
    logger.info("MCP server mounted at /mcp (streamable-http)")

    # FastMCP requires its own lifespan to be run so that the
    # StreamableHTTPSessionManager task group is initialized before requests arrive.
    # FastAPI does not automatically propagate lifespan to mounted sub-apps,
    # so the application lifespan enters/exits this context manager directly.
    mcp_lifespan_ctx = mcp_http_app.router.lifespan_context(mcp_http_app)
    return mcp_lifespan_ctx
