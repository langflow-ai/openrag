"""OpenRAG MCP tools."""

from openrag_mcp.tools.chat import get_chat_tools, handle_chat_tool
from openrag_mcp.tools.search import get_search_tools, handle_search_tool
from openrag_mcp.tools.documents import get_document_tools, handle_document_tool

__all__ = [
    "get_chat_tools",
    "handle_chat_tool",
    "get_search_tools",
    "handle_search_tool",
    "get_document_tools",
    "handle_document_tool",
]
