"""Dynamic MCP server that exposes generated widgets as tools."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import mcp.types as types
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from utils.logging_config import get_logger

logger = get_logger(__name__)

MIME_TYPE = "text/html+skybridge"


@dataclass(frozen=True)
class MCPWidget:
    """Data model representing a widget exposed via MCP."""

    widget_id: str
    identifier: str
    title: str
    template_uri: str
    invoking: str
    invoked: str
    response_text: str
    has_css: bool

    def build_html(self) -> str:
        """Return the HTML shell that loads the built widget bundle."""
        lines = ['<div id="root"></div>']
        if self.has_css:
            lines.append(f'<link rel="stylesheet" href="/widgets/assets/{self.widget_id}.css">')
        lines.append(f'<script type="module" src="/widgets/assets/{self.widget_id}.js"></script>')
        return "\n".join(lines)


class WidgetInvocation(BaseModel):
    """Schema for widget invocation."""

    data: Dict[str, Any] | None = Field(
        default=None,
        description="Optional JSON payload forwarded to the widget.",
    )

    model_config = ConfigDict(extra="forbid")


TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "data": {
            "type": "object",
            "description": "Optional JSON payload forwarded to the widget as structured content.",
        }
    },
    "additionalProperties": False,
}


class WidgetMCPServer:
    """Manages a FastMCP server that surfaces widgets as MCP tools."""

    def __init__(self, name: str = "openrag-widgets"):
        self._mcp = FastMCP(
            name=name,
            sse_path="/mcp",
            message_path="/mcp/messages",
            stateless_http=True,
        )
        self.app = self._mcp.streamable_http_app()
        self._widgets_by_id: Dict[str, MCPWidget] = {}
        self._widgets_by_uri: Dict[str, MCPWidget] = {}
        self._lifespan_ctx: Optional[asynccontextmanager] = None
        self._lifespan_token: Optional[Any] = None

        self._register_handlers()
        self._configure_cors()

    # --- Public API -----------------------------------------------------
    def replace_widgets(self, widget_payloads: List[Dict[str, Any]]) -> None:
        """Replace all widgets exposed by the MCP server."""
        logger.info("Replacing MCP widgets", widget_count=len(widget_payloads))
        self._widgets_by_id.clear()
        self._widgets_by_uri.clear()

        for payload in widget_payloads:
            widget = MCPWidget(
                widget_id=payload["widget_id"],
                identifier=payload["identifier"],
                title=payload["title"],
                template_uri=payload["template_uri"],
                invoking=payload["invoking"],
                invoked=payload["invoked"],
                response_text=payload["response_text"],
                has_css=payload.get("has_css", False),
            )
            self._widgets_by_id[widget.identifier] = widget
            self._widgets_by_uri[widget.template_uri] = widget

    def upsert_widget(self, payload: Dict[str, Any]) -> None:
        """Insert or update a widget exposed via MCP."""
        widget = MCPWidget(
            widget_id=payload["widget_id"],
            identifier=payload["identifier"],
            title=payload["title"],
            template_uri=payload["template_uri"],
            invoking=payload["invoking"],
            invoked=payload["invoked"],
            response_text=payload["response_text"],
            has_css=payload.get("has_css", False),
        )
        logger.info("Upserting MCP widget", widget_id=widget.widget_id)
        self._widgets_by_id[widget.identifier] = widget
        self._widgets_by_uri[widget.template_uri] = widget

    def remove_widget(self, widget_id: str) -> None:
        """Remove a widget from the MCP registry by widget id."""
        identifier_to_remove: Optional[str] = None
        uri_to_remove: Optional[str] = None

        for identifier, widget in self._widgets_by_id.items():
            if widget.widget_id == widget_id:
                identifier_to_remove = identifier
                break

        if identifier_to_remove:
            widget = self._widgets_by_id.pop(identifier_to_remove)
            logger.info("Removed MCP widget", widget_id=widget.widget_id)
            uri_to_remove = widget.template_uri

        if uri_to_remove and uri_to_remove in self._widgets_by_uri:
            self._widgets_by_uri.pop(uri_to_remove, None)

    async def startup(self) -> None:
        """Start the FastMCP app lifespan so streamable HTTP works."""
        if self._lifespan_ctx is None:
            self._lifespan_ctx = self.app.router.lifespan_context(self.app)
            self._lifespan_token = await self._lifespan_ctx.__aenter__()

    async def shutdown(self) -> None:
        """Stop the FastMCP app lifespan."""
        if self._lifespan_ctx is not None:
            await self._lifespan_ctx.__aexit__(None, None, None)
            self._lifespan_ctx = None
            self._lifespan_token = None

    # --- Internal helpers ------------------------------------------------
    def _register_handlers(self) -> None:
        server = self._mcp._mcp_server

        @server.list_tools()
        async def _list_tools() -> List[types.Tool]:
            return [
                types.Tool(
                    name=widget.identifier,
                    title=widget.title,
                    description=widget.title,
                    inputSchema=deepcopy(TOOL_INPUT_SCHEMA),
                    _meta=self._tool_meta(widget),
                )
                for widget in self._widgets_by_id.values()
            ]

        @server.list_resources()
        async def _list_resources() -> List[types.Resource]:
            return [
                types.Resource(
                    name=widget.title,
                    title=widget.title,
                    uri=widget.template_uri,
                    description=self._resource_description(widget),
                    mimeType=MIME_TYPE,
                    _meta=self._tool_meta(widget),
                )
                for widget in self._widgets_by_uri.values()
            ]

        @server.list_resource_templates()
        async def _list_resource_templates() -> List[types.ResourceTemplate]:
            return [
                types.ResourceTemplate(
                    name=widget.title,
                    title=widget.title,
                    uriTemplate=widget.template_uri,
                    description=self._resource_description(widget),
                    mimeType=MIME_TYPE,
                    _meta=self._tool_meta(widget),
                )
                for widget in self._widgets_by_uri.values()
            ]

        async def _handle_read_resource(
            req: types.ReadResourceRequest,
        ) -> types.ServerResult:
            widget = self._widgets_by_uri.get(str(req.params.uri))
            if widget is None:
                return types.ServerResult(
                    types.ReadResourceResult(
                        contents=[],
                        _meta={"error": f"Unknown resource: {req.params.uri}"},
                    )
                )

            contents = [
                types.TextResourceContents(
                    uri=widget.template_uri,
                    mimeType=MIME_TYPE,
                    text=widget.build_html(),
                    _meta=self._tool_meta(widget),
                )
            ]
            return types.ServerResult(types.ReadResourceResult(contents=contents))

        async def _call_tool_request(
            req: types.CallToolRequest,
        ) -> types.ServerResult:
            widget = self._widgets_by_id.get(req.params.name)
            if widget is None:
                return types.ServerResult(
                    types.CallToolResult(
                        content=[
                            types.TextContent(
                                type="text",
                                text=f"Unknown tool: {req.params.name}",
                            )
                        ],
                        isError=True,
                    )
                )

            arguments = req.params.arguments or {}
            try:
                payload = WidgetInvocation.model_validate(arguments)
            except ValidationError as exc:
                return types.ServerResult(
                    types.CallToolResult(
                        content=[
                            types.TextContent(
                                type="text",
                                text=f"Input validation error: {exc.errors()}",
                            )
                        ],
                        isError=True,
                    )
                )

            structured_content = payload.data or {}
            structured_content.setdefault("widgetId", widget.widget_id)
            structured_content.setdefault("templateUri", widget.template_uri)

            embedded_resource = types.EmbeddedResource(
                type="resource",
                resource=types.TextResourceContents(
                    uri=widget.template_uri,
                    mimeType=MIME_TYPE,
                    text=widget.build_html(),
                    title=widget.title,
                ),
            )

            meta: Dict[str, Any] = {
                "openai.com/widget": embedded_resource.model_dump(mode="json"),
                "openai/outputTemplate": widget.template_uri,
                "openai/toolInvocation/invoking": widget.invoking,
                "openai/toolInvocation/invoked": widget.invoked,
                "openai/widgetAccessible": True,
                "openai/resultCanProduceWidget": True,
            }

            return types.ServerResult(
                types.CallToolResult(
                    content=[
                        types.TextContent(
                            type="text",
                            text=widget.response_text,
                        )
                    ],
                    structuredContent=structured_content,
                    _meta=meta,
                )
            )

        server.request_handlers[types.ReadResourceRequest] = _handle_read_resource
        server.request_handlers[types.CallToolRequest] = _call_tool_request

    def _configure_cors(self) -> None:
        try:
            from starlette.middleware.cors import CORSMiddleware

            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
                allow_credentials=False,
            )
        except Exception:
            logger.debug("CORS middleware not added for Widget MCP server")

    @staticmethod
    def _resource_description(widget: MCPWidget) -> str:
        return f"{widget.title} widget markup"

    @staticmethod
    def _tool_meta(widget: MCPWidget) -> Dict[str, Any]:
        return {
            "openai/outputTemplate": widget.template_uri,
            "openai/toolInvocation/invoking": widget.invoking,
            "openai/toolInvocation/invoked": widget.invoked,
            "openai/widgetAccessible": True,
            "openai/resultCanProduceWidget": True,
            "annotations": {
                "destructiveHint": False,
                "openWorldHint": False,
                "readOnlyHint": True,
            },
        }
