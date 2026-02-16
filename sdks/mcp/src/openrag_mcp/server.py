"""OpenRAG MCP Server - Main server setup and entry point."""
# Note: The MCP server is currently configured explicitly rather than being driven
# directly by the OpenRAG SDK, so changes to SDK parameters must be reflected here manually.

import asyncio
import logging
import os

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from openrag_mcp.config import get_config

# Import tools module to trigger registration, then get registry functions
from openrag_mcp.tools import get_all_tools, get_handler

# Configure logging to stderr (stdout is used for MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("openrag-mcp")


def create_server() -> Server:
    """Create and configure the MCP server with all tools registered."""
    # Validate configuration early
    config = get_config()
    logger.info(f"Connecting to OpenRAG at {config.openrag_url}")

    # Create server instance
    server = Server("openrag-mcp")

    @server.list_tools()
    async def list_all_tools() -> list[Tool]:
        """List all available tools."""
        return get_all_tools()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle all tool calls by dispatching to the appropriate handler."""
        handler = get_handler(name)
        if handler:
            return await handler(arguments)
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    logger.info("OpenRAG MCP server initialized with all tools")
    return server


async def run_stdio_server():
    """Run the MCP server with stdio transport."""
    server = create_server()

    async with stdio_server() as (read_stream, write_stream):
        logger.info("Starting OpenRAG MCP server with stdio transport")
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def run_sse_server():
    """Run the MCP server with SSE transport (for Docker / network access)."""
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Mount, Route

    server = create_server()
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
        return Response()

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )

    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8080"))
    logger.info(f"Starting OpenRAG MCP server with SSE transport on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


def main():
    """Entry point for the MCP server."""
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()

    try:
        if transport == "sse":
            run_sse_server()
        else:
            asyncio.run(run_stdio_server())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except ValueError as e:
        # Configuration errors
        logger.error(f"Configuration error: {e}")
        raise SystemExit(1)
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
