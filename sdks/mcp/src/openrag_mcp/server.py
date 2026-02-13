"""OpenRAG MCP Server - Main server setup and entry point."""
# Note: The MCP server is currently configured explicitly rather than being driven
# directly by the OpenRAG SDK, so changes to SDK parameters must be reflected here manually.

import asyncio
import logging

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


async def run_server():
    """Run the MCP server with stdio transport."""
    server = create_server()

    async with stdio_server() as (read_stream, write_stream):
        logger.info("Starting OpenRAG MCP server with stdio transport")
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    """Entry point for the MCP server."""
    try:
        asyncio.run(run_server())
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
