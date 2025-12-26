"""Chat tool for OpenRAG MCP server."""

import logging

from mcp.types import TextContent, Tool

from openrag_sdk import (
    AuthenticationError,
    OpenRAGError,
    RateLimitError,
    ServerError,
    ValidationError,
)

from openrag_mcp.config import get_openrag_client
from openrag_mcp.tools.registry import register_tool

logger = logging.getLogger("openrag-mcp.chat")


# Tool definition
CHAT_TOOL = Tool(
    name="openrag_chat",
    description=(
        "Send a message to OpenRAG and get a RAG-enhanced response. "
        "The response is informed by documents in your knowledge base. "
        "Use chat_id to continue a previous conversation, or filter_id "
        "to apply a knowledge filter."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Your question or message to send to OpenRAG",
            },
            "chat_id": {
                "type": "string",
                "description": "Optional conversation ID to continue a previous chat",
            },
            "filter_id": {
                "type": "string",
                "description": "Optional knowledge filter ID to apply",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of sources to retrieve (default: 10)",
                "default": 10,
            },
            "score_threshold": {
                "type": "number",
                "description": "Minimum relevance score threshold (default: 0)",
                "default": 0,
            },
        },
        "required": ["message"],
    },
)


async def handle_chat(arguments: dict) -> list[TextContent]:
    """Handle openrag_chat tool calls."""
    message = arguments.get("message", "")
    chat_id = arguments.get("chat_id")
    filter_id = arguments.get("filter_id")
    limit = arguments.get("limit", 10)
    score_threshold = arguments.get("score_threshold", 0)

    if not message:
        return [TextContent(type="text", text="Error: message is required")]

    try:
        client = get_openrag_client()
        response = await client.chat.create(
            message=message,
            chat_id=chat_id,
            filter_id=filter_id,
            limit=limit,
            score_threshold=score_threshold,
        )

        # Build formatted response
        output_parts = [response.response]

        if response.sources:
            output_parts.append("\n\n---\n**Sources:**")
            for i, source in enumerate(response.sources, 1):
                output_parts.append(f"\n{i}. {source.filename} (relevance: {source.score:.2f})")

        if response.chat_id:
            output_parts.append(f"\n\n_Chat ID: {response.chat_id}_")

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
        logger.error(f"Chat error: {e}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


# Register the tool
register_tool(CHAT_TOOL, handle_chat)
