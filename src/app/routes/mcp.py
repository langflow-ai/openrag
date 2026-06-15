"""FastMCP streamable-HTTP server mounted at /mcp.

Returns the MCP http_app's lifespan context manager so the application
lifespan can enter/exit it inline (FastAPI does not propagate lifespan
to mounted sub-apps automatically).
"""

from fastapi import FastAPI

from mcp_http.server import create_mcp_server
from utils.logging_config import get_logger

logger = get_logger(__name__)


class _ForwardJWTToMCPMiddleware:
    """ASGI shim: copy the inbound ``Authorization`` JWT into a non-excluded
    header so it survives FastMCP's proxy to the underlying /v1 handler.

    FastMCP's ``get_http_headers()`` strips ``authorization`` from the headers
    it forwards when an MCP tool re-invokes a /v1 route, so a gateway-forwarded
    JWT would otherwise be lost (the client then falls back to lakehouse creds,
    which OpenSearch rejects with 401 and which carry no RBAC roles -> 403).
    We *copy* (not move) the value into ``OPENRAG_MCP_JWT_HEADER`` (default
    ``X-OpenRAG-JWT``), which is not in FastMCP's exclude set; the original
    header is left intact. ``get_api_key_user_async`` reads it as a fallback.

    Scoped to the /mcp sub-app only, so normal /v1 and UI traffic is untouched.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from config.settings import get_mcp_forwarded_jwt_header

        target = get_mcp_forwarded_jwt_header().lower().encode("latin-1")
        headers = scope.get("headers", [])
        auth = None
        has_target = False
        for name, value in headers:
            lname = name.lower()
            if lname == b"authorization":
                auth = value
            elif lname == target:
                has_target = True
        if auth is not None and not has_target:
            scope = dict(scope)
            scope["headers"] = list(headers) + [(target, auth)]
        await self.app(scope, receive, send)


def mount_mcp(app: FastAPI):
    """Mount the FastMCP app at /mcp and return its lifespan context manager."""
    logger.info("Creating MCP server")
    mcp_server = create_mcp_server(app)
    mcp_http_app = mcp_server.http_app(transport="streamable-http", path="/")
    app.mount("/mcp", _ForwardJWTToMCPMiddleware(mcp_http_app))
    logger.info("MCP server mounted at /mcp (streamable-http)")

    # FastMCP requires its own lifespan to be run so that the
    # StreamableHTTPSessionManager task group is initialized before requests arrive.
    # FastAPI does not automatically propagate lifespan to mounted sub-apps,
    # so the application lifespan enters/exits this context manager directly.
    mcp_lifespan_ctx = mcp_http_app.router.lifespan_context(mcp_http_app)
    return mcp_lifespan_ctx
