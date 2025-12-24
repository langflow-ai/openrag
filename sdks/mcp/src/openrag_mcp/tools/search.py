"""Search tool for OpenRAG MCP server."""

import logging

from mcp.server import Server
from mcp.types import TextContent, Tool

from openrag_mcp.config import get_client

logger = logging.getLogger("openrag-mcp.search")


def register_search_tools(server: Server) -> None:
    """Register search-related tools with the MCP server."""

    @server.list_tools()
    async def list_search_tools() -> list[Tool]:
        """List search tools."""
        return [
            Tool(
                name="openrag_search",
                description=(
                    "Search the OpenRAG knowledge base using semantic search. "
                    "Returns matching document chunks with relevance scores."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results (default: 10)",
                            "default": 10,
                        },
                    },
                    "required": ["query"],
                },
            ),
        ]

    @server.call_tool()
    async def call_search_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle search tool calls."""
        if name != "openrag_search":
            return []

        query = arguments.get("query", "")
        limit = arguments.get("limit", 10)

        if not query:
            return [TextContent(type="text", text="Error: query is required")]

        try:
            async with get_client() as client:
                payload = {
                    "query": query,
                    "limit": limit,
                }

                response = await client.post("/api/v1/search", json=payload)
                response.raise_for_status()
                data = response.json()

                results = data.get("results", [])

                if not results:
                    return [TextContent(type="text", text="No results found.")]

                # Format results
                output_parts = [f"Found {len(results)} result(s):\n"]

                for i, result in enumerate(results, 1):
                    filename = result.get("filename", "Unknown")
                    score = result.get("score", 0)
                    content = result.get("content", "")
                    page = result.get("page_number")

                    output_parts.append(f"\n---\n**{i}. {filename}**")
                    if page:
                        output_parts.append(f" (page {page})")
                    output_parts.append(f"\nRelevance: {score:.2f}\n")

                    # Truncate long content
                    if len(content) > 500:
                        content = content[:500] + "..."
                    output_parts.append(f"\n{content}\n")

                return [TextContent(type="text", text="".join(output_parts))]

        except Exception as e:
            logger.error(f"Search error: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

