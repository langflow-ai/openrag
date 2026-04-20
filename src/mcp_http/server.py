"""
FastMCP streamable HTTP server integration.

Exposes all /v1/ FastAPI endpoints as MCP tools over streamable HTTP transport.
Auth headers passed by MCP clients are forwarded transparently to the underlying
FastAPI endpoint handlers via FastMCP's internal proxy.

Supported authentication methods:

1. OpenRAG API Key:
   - X-API-Key: orag_...
   - Authorization: Bearer orag_...

2. IBM Auth (when IBM_AUTH_ENABLED=true):
   - X-Username: <ibm_username>
   - X-Api-Key: <ibm_api_key>

Usage (MCP client config):

    Standard API key:
    {
      "mcpServers": {
        "openrag": {
          "url": "http://localhost:8000/mcp",
          "headers": { "X-API-Key": "orag_..." }
        }
      }
    }

    IBM auth:
    {
      "mcpServers": {
        "openrag": {
          "url": "http://localhost:8000/mcp",
          "headers": {
            "X-Username": "your_ibm_username",
            "X-Api-Key": "your_ibm_api_key"
          }
        }
      }
    }
"""
from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import (
    MCPType,
    OpenAPIResource,
    OpenAPIResourceTemplate,
    OpenAPITool,
    RouteMap,
)
from fastmcp.server.providers.openapi.routing import HTTPRoute
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Tool/resource customizations: map (path, method) to custom name and description
COMPONENT_CUSTOMIZATIONS: dict[tuple[str, str], dict[str, str]] = {
    # Chat endpoints
    ("/v1/chat", "POST"): {
        "name": "openrag_chat",
        "description": (
            "Send a message to OpenRAG and get a RAG-enhanced response. "
            "The response is informed by documents in your knowledge base. "
            "Use chat_id to continue a previous conversation, or filter_id "
            "to apply a knowledge filter."
        ),
    },
    ("/v1/chat", "GET"): {
        "name": "openrag_list_chats",
        "description": "List all chat conversations.",
    },
    ("/v1/chat/{chat_id}", "GET"): {
        "name": "openrag_get_chat",
        "description": "Get a specific chat conversation by ID.",
    },
    ("/v1/chat/{chat_id}", "DELETE"): {
        "name": "openrag_delete_chat",
        "description": "Delete a chat conversation by ID.",
    },
    # Search endpoint
    ("/v1/search", "POST"): {
        "name": "openrag_search",
        "description": (
            "Search the OpenRAG knowledge base using semantic search. "
            "Returns matching document chunks with relevance scores. "
            "Optionally filter by data sources or document types."
        ),
    },
    # Documents endpoints
    ("/v1/documents/ingest", "POST"): {
        "name": "openrag_ingest",
        "description": (
            "Ingest documents into the OpenRAG knowledge base. "
            "Supports file uploads, URLs, and text content. "
            "Returns a task_id for tracking ingestion progress."
        ),
    },
    ("/v1/tasks/{task_id}", "GET"): {
        "name": "openrag_get_task_status",
        "description": (
            "Check the status of an ingestion task. "
            "Use the task_id returned from openrag_ingest."
        ),
    },
    ("/v1/documents", "DELETE"): {
        "name": "openrag_delete_document",
        "description": "Delete a document from the OpenRAG knowledge base by filename.",
    },
    # Settings endpoints
    ("/v1/settings", "GET"): {
        "name": "openrag_get_settings",
        "description": (
            "Get the current OpenRAG configuration. Returns LLM provider and model, "
            "embedding provider and model, chunk settings, document processing options "
            "(table structure, OCR, picture descriptions), and system prompt."
        ),
    },
    ("/v1/settings", "POST"): {
        "name": "openrag_update_settings",
        "description": (
            "Update OpenRAG configuration. All parameters are optional; only provided "
            "fields are changed. Use this to set LLM model, embedding model, chunk size/overlap, "
            "system prompt, and document processing options."
        ),
    },
    # Models endpoint
    ("/v1/models/{provider}", "GET"): {
        "name": "openrag_list_models",
        "description": (
            "List available language models and embedding models for a provider. "
            "Use this before updating settings to see which model values are valid. "
            "Provider must be one of: openai, anthropic, ollama, watsonx."
        ),
    },
    # Knowledge filters endpoints
    ("/v1/knowledge-filters", "POST"): {
        "name": "openrag_create_knowledge_filter",
        "description": (
            "Create a new knowledge filter to scope searches and chats "
            "to specific documents or data sources."
        ),
    },
    ("/v1/knowledge-filters/search", "POST"): {
        "name": "openrag_search_knowledge_filters",
        "description": "Search for knowledge filters by name or other criteria.",
    },
    ("/v1/knowledge-filters/{filter_id}", "GET"): {
        "name": "openrag_get_knowledge_filter",
        "description": "Get a specific knowledge filter by ID.",
    },
    ("/v1/knowledge-filters/{filter_id}", "PUT"): {
        "name": "openrag_update_knowledge_filter",
        "description": "Update an existing knowledge filter.",
    },
    ("/v1/knowledge-filters/{filter_id}", "DELETE"): {
        "name": "openrag_delete_knowledge_filter",
        "description": "Delete a knowledge filter by ID.",
    },
}


def _customize_mcp_component(
    route: HTTPRoute,
    component: OpenAPITool | OpenAPIResource | OpenAPIResourceTemplate,
) -> None:
    """
    Customize MCP component names and descriptions based on route.

    This function is called by FastMCP after each component is created,
    allowing us to set friendly names and detailed descriptions similar
    to how tools are defined in the SDK MCP server.
    """
    key = (route.path, route.method.upper())
    if key in COMPONENT_CUSTOMIZATIONS:
        config = COMPONENT_CUSTOMIZATIONS[key]
        if "name" in config:
            component.name = config["name"]
        if "description" in config:
            component.description = config["description"]


def create_mcp_server(app: FastAPI) -> FastMCP:
    """
    Build a FastMCP server from the FastAPI app, exposing only /v1/ routes as tools.

    Must be called AFTER all routes are registered on `app` so that
    FastMCP.from_fastapi() can discover them.

    Route mapping:
    - /v1/* routes → MCP tools (POST, PUT, DELETE, PATCH)
    - /v1/* routes → MCP resource templates (GET with path params)
    - /v1/* routes → MCP resources (GET without path params)
    - All other routes → excluded
    """
    route_maps = [
        # Expose all /v1/ GET routes with path params as resource templates
        RouteMap(
            methods=["GET"],
            pattern=r"^/v1/",
            mcp_type=MCPType.RESOURCE_TEMPLATE,
        ),
        # Expose all /v1/ GET routes without path params as resources
        RouteMap(
            methods=["GET"],
            pattern=r"^/v1/",
            mcp_type=MCPType.RESOURCE,
        ),
        # Expose all /v1/ mutating routes as tools
        RouteMap(
            methods=["POST", "PUT", "DELETE", "PATCH"],
            pattern=r"^/v1/",
            mcp_type=MCPType.TOOL,
        ),
        # Exclude everything else
        RouteMap(
            pattern=r".*",
            mcp_type=MCPType.EXCLUDE,
        ),
    ]

    mcp = FastMCP.from_fastapi(
        app=app,
        name="OpenRAG",
        route_maps=route_maps,
        mcp_component_fn=_customize_mcp_component,
    )
    logger.info("FastMCP streamable HTTP server created")
    return mcp
