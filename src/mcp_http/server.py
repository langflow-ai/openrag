"""
FastMCP streamable HTTP server integration.

Exposes all /v1/ FastAPI endpoints as MCP tools over streamable HTTP transport.
Auth headers (X-API-Key) passed by MCP clients are forwarded transparently to
the underlying FastAPI endpoint handlers via FastMCP's internal proxy.

Usage (MCP client config):
    {
      "mcpServers": {
        "openrag": {
          "url": "http://localhost:8000/mcp",
          "headers": { "X-API-Key": "orag_..." }
        }
      }
    }
"""
from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import RouteMap, MCPType
from utils.logging_config import get_logger

logger = get_logger(__name__)


def create_mcp_server(app: FastAPI) -> FastMCP:
    """
    Build a FastMCP server from the FastAPI app, exposing only /v1/ routes as tools.

    Must be called AFTER all routes are registered on `app` so that
    FastMCP.from_fastapi() can discover them.

    Route mapping:
    - /v1/* routes → MCP tools (POST, PUT, DELETE, PATCH)
    - /v1/* routes → MCP resource templates (GET with path params)
    - /v1/* routes → MCP resources (GET without path params)
    - All other routes → excluded
    """
    route_maps = [
        # Expose all /v1/ GET routes with path params as resource templates
        RouteMap(
            methods=["GET"],
            pattern=r"^/v1/",
            mcp_type=MCPType.RESOURCE_TEMPLATE,
        ),
        # Expose all /v1/ GET routes without path params as resources
        RouteMap(
            methods=["GET"],
            pattern=r"^/v1/",
            mcp_type=MCPType.RESOURCE,
        ),
        # Expose all /v1/ mutating routes as tools
        RouteMap(
            methods=["POST", "PUT", "DELETE", "PATCH"],
            pattern=r"^/v1/",
            mcp_type=MCPType.TOOL,
        ),
        # Exclude everything else
        RouteMap(
            pattern=r".*",
            mcp_type=MCPType.EXCLUDE,
        ),
    ]

    mcp = FastMCP.from_fastapi(
        app=app,
        name="OpenRAG",
        route_maps=route_maps,
    )
    logger.info("FastMCP streamable HTTP server created")
    return mcp
