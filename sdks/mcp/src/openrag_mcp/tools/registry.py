"""Tool registry for OpenRAG MCP server."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from mcp.types import TextContent, Tool

# Type alias for tool handlers
ToolHandler = Callable[[dict], Awaitable[list[TextContent]]]


@dataclass
class ToolEntry:
    """A tool definition with its handler."""
    tool: Tool
    handler: ToolHandler


# Global registry: tool_name -> ToolEntry
_registry: dict[str, ToolEntry] = {}


def register_tool(tool: Tool, handler: ToolHandler) -> None:
    """Register a tool with its handler."""
    _registry[tool.name] = ToolEntry(tool=tool, handler=handler)


def get_all_tools() -> list[Tool]:
    """Get all registered tools."""
    return [entry.tool for entry in _registry.values()]


def get_handler(name: str) -> ToolHandler | None:
    """Get the handler for a tool by name."""
    entry = _registry.get(name)
    return entry.handler if entry else None

