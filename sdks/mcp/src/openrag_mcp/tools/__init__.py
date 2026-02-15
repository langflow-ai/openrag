"""OpenRAG MCP tools.

Import this module to register all tools with the registry.
"""

# Import tools to trigger registration
from openrag_mcp.tools import chat  # noqa: F401
from openrag_mcp.tools import search  # noqa: F401
from openrag_mcp.tools import documents  # noqa: F401
from openrag_mcp.tools import settings  # noqa: F401

# Re-export registry functions for convenience
from openrag_mcp.tools.registry import get_all_tools, get_handler

__all__ = ["get_all_tools", "get_handler"]
