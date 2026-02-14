"""Search tool for OpenRAG MCP server."""

import logging

from mcp.types import TextContent, Tool

from openrag_sdk import (
    AuthenticationError,
    OpenRAGError,
    RateLimitError,
    SearchFilters,
    ServerError,
    ValidationError,
)

from openrag_mcp.config import get_openrag_client
from openrag_mcp.tools.registry import register_tool

logger = logging.getLogger("openrag-mcp.search")


# Tool definition
SEARCH_TOOL = Tool(
    name="openrag_search",
    description=(
        "Search the OpenRAG knowledge base using semantic search. "
        "Returns matching document chunks with relevance scores. "
        "Optionally filter by data sources or document types."
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
            "score_threshold": {
                "type": "number",
                "description": "Minimum relevance score threshold (default: 0)",
                "default": 0,
            },
            "filter_id": {
                "type": "string",
                "description": "Optional knowledge filter ID to apply",
            },
            "data_sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of filenames to filter by",
            },
            "document_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of MIME types to filter by (e.g., 'application/pdf')",
            },
        },
        "required": ["query"],
    },
)


async def handle_search(arguments: dict) -> list[TextContent]:
    """Handle openrag_search tool calls."""
    query = arguments.get("query", "")
    limit = arguments.get("limit", 10)
    score_threshold = arguments.get("score_threshold", 0)
    filter_id = arguments.get("filter_id")
    data_sources = arguments.get("data_sources")
    document_types = arguments.get("document_types")

    if not query:
        return [TextContent(type="text", text="Error: query is required")]

    try:
        client = get_openrag_client()

        # Build filters if provided
        filters = None
        if data_sources or document_types:
            filters = SearchFilters(
                data_sources=data_sources,
                document_types=document_types,
            )

        response = await client.search.query(
            query=query,
            limit=limit,
            score_threshold=score_threshold,
            filter_id=filter_id,
            filters=filters,
        )

        if not response.results:
            return [TextContent(type="text", text="No results found.")]

        # Format results
        output_parts = [f"Found {len(response.results)} result(s):\n"]

        for i, result in enumerate(response.results, 1):
            output_parts.append(f"\n---\n**{i}. {result.filename}**")
            if result.page:
                output_parts.append(f" (page {result.page})")
            output_parts.append(f"\nRelevance: {result.score:.2f}\n")

            # Truncate long content
            content = result.text
            if len(content) > 500:
                content = content[:500] + "..."
            output_parts.append(f"\n{content}\n")

        return [TextContent(type="text", text="".join(output_parts))]

    except AuthenticationError as e:
        logger.error(f"Authentication error: {e.message}")
        return [TextContent(type="text", text=f"Authentication error: {e.message}")]
    except ValidationError as e:
        logger.error(f"Validation error: {e.message}")
        return [TextContent(type="text", text=f"Invalid request: {e.message}")]
    except RateLimitError as e:
        logger.error(f"Rate limit error: {e.message}")
        return [TextContent(type="text", text=f"Rate limited: {e.message}")]
    except ServerError as e:
        logger.error(f"Server error: {e.message}")
        return [TextContent(type="text", text=f"Server error: {e.message}")]
    except OpenRAGError as e:
        logger.error(f"OpenRAG error: {e.message}")
        return [TextContent(type="text", text=f"Error: {e.message}")]
    except Exception as e:
        logger.error(f"Search error: {e}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


# Register the tool
register_tool(SEARCH_TOOL, handle_search)
