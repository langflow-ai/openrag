"""Chat tool for OpenRAG MCP server."""

import json
import logging

from mcp.server import Server
from mcp.types import TextContent, Tool

from openrag_mcp.config import get_client

logger = logging.getLogger("openrag-mcp.chat")


def register_chat_tools(server: Server) -> None:
    """Register chat-related tools with the MCP server."""

    @server.list_tools()
    async def list_chat_tools() -> list[Tool]:
        """List chat tools."""
        return [
            Tool(
                name="openrag_chat",
                description=(
                    "Send a message to OpenRAG and get a RAG-enhanced response. "
                    "The response is informed by documents in your knowledge base. "
                    "Use chat_id to continue a previous conversation."
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
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of sources to retrieve (default: 10)",
                            "default": 10,
                        },
                    },
                    "required": ["message"],
                },
            ),
        ]

    @server.call_tool()
    async def call_chat_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle chat tool calls."""
        if name != "openrag_chat":
            return []

        message = arguments.get("message", "")
        chat_id = arguments.get("chat_id")
        limit = arguments.get("limit", 10)

        if not message:
            return [TextContent(type="text", text="Error: message is required")]

        try:
            async with get_client() as client:
                payload = {
                    "message": message,
                    "stream": False,
                    "limit": limit,
                }
                if chat_id:
                    payload["chat_id"] = chat_id

                response = await client.post("/api/v1/chat", json=payload)
                response.raise_for_status()
                data = response.json()

                # Format the response
                result_text = data.get("response", "")
                sources = data.get("sources", [])
                new_chat_id = data.get("chat_id")

                # Build formatted response
                output_parts = [result_text]

                if sources:
                    output_parts.append("\n\n---\n**Sources:**")
                    for i, source in enumerate(sources, 1):
                        filename = source.get("filename", "Unknown")
                        score = source.get("score", 0)
                        output_parts.append(f"\n{i}. {filename} (relevance: {score:.2f})")

                if new_chat_id:
                    output_parts.append(f"\n\n_Chat ID: {new_chat_id}_")

                return [TextContent(type="text", text="".join(output_parts))]

        except Exception as e:
            logger.error(f"Chat error: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

