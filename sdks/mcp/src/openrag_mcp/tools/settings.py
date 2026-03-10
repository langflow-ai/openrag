"""Settings and models tools for OpenRAG MCP server.

Uses direct HTTP calls so these tools work with any OpenRAG backend,
without depending on SDK version (models client or settings model fields).
"""

import logging

from mcp.types import TextContent, Tool

from openrag_mcp.config import get_client
from openrag_mcp.tools.registry import register_tool

logger = logging.getLogger("openrag-mcp.settings")

VALID_PROVIDERS = ("openai", "anthropic", "ollama", "watsonx")

def _format_http_error(response) -> str:
    """Extract error message from HTTP response."""
    try:
        data = response.json()
        return data.get("error", response.text) or f"HTTP {response.status_code}"
    except Exception:
        return response.text or f"HTTP {response.status_code}"


async def _request_get(path_with_api: str, path_without_api: str):
    """GET request; try /api/v1/... first, then /v1/... on 404 (backend-only)."""
    http = get_client()
    response = await http.get(path_with_api)
    if response.status_code == 404 and path_with_api.startswith("/api"):
        response = await http.get(path_without_api)
    return response


async def _request_post(path_with_api: str, path_without_api: str, json_body: dict):
    """POST request; try /api/v1/... first, then /v1/... on 404."""
    http = get_client()
    response = await http.post(path_with_api, json=json_body)
    if response.status_code == 404 and path_with_api.startswith("/api"):
        response = await http.post(path_without_api, json=json_body)
    return response


# ============================================================================
# Tool: openrag_get_settings
# ============================================================================

GET_SETTINGS_TOOL = Tool(
    name="openrag_get_settings",
    description=(
        "Get the current OpenRAG configuration. Returns LLM provider and model, "
        "embedding provider and model, chunk settings, document processing options "
        "(table structure, OCR, picture descriptions), and system prompt."
    ),
    inputSchema={
        "type": "object",
        "properties": {},
    },
)


async def handle_get_settings(arguments: dict) -> list[TextContent]:
    """Handle openrag_get_settings tool calls."""
    try:
        response = await _request_get("/api/v1/settings", "/v1/settings")
        if response.status_code != 200:
            return [TextContent(type="text", text=_format_http_error(response))]

        data = response.json()
        agent = data.get("agent") or {}
        knowledge = data.get("knowledge") or {}

        parts = ["**Current OpenRAG settings**\n"]
        parts.append("\n**Agent (LLM)**")
        parts.append(f"\n- Provider: {agent.get('llm_provider') or '—'}")
        parts.append(f"\n- Model: {agent.get('llm_model') or '—'}")
        system_prompt = agent.get("system_prompt")
        if system_prompt:
            prompt_preview = (
                system_prompt[:200] + "..." if len(system_prompt) > 200 else system_prompt
            )
            parts.append(f"\n- System prompt: {prompt_preview}")
        parts.append("\n**Knowledge (embeddings & ingestion)**")
        parts.append(f"\n- Embedding provider: {knowledge.get('embedding_provider') or '—'}")
        parts.append(f"\n- Embedding model: {knowledge.get('embedding_model') or '—'}")
        parts.append(f"\n- Chunk size: {knowledge.get('chunk_size', '—')}")
        parts.append(f"\n- Chunk overlap: {knowledge.get('chunk_overlap', '—')}")
        if "table_structure" in knowledge:
            parts.append(f"\n- Table structure: {knowledge['table_structure']}")
        if "ocr" in knowledge:
            parts.append(f"\n- OCR: {knowledge['ocr']}")
        if "picture_descriptions" in knowledge:
            parts.append(f"\n- Picture descriptions: {knowledge['picture_descriptions']}")

        return [TextContent(type="text", text="".join(parts))]

    except Exception as e:
        logger.error("Get settings error: %s", e)
        return [TextContent(type="text", text=f"Error getting settings: {str(e)}")]


# ============================================================================
# Tool: openrag_update_settings
# ============================================================================

UPDATE_SETTINGS_TOOL = Tool(
    name="openrag_update_settings",
    description=(
        "Update OpenRAG configuration. All parameters are optional; only provided "
        "fields are changed. Use this to set LLM model, embedding model, chunk size/overlap, "
        "system prompt, and document processing options (table structure, OCR, picture descriptions)."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "llm_provider": {
                "type": "string",
                "description": "LLM provider: openai, anthropic, watsonx, or ollama",
            },
            "llm_model": {
                "type": "string",
                "description": "Language model name (e.g. gpt-4o, claude-sonnet-4)",
            },
            "embedding_provider": {
                "type": "string",
                "description": "Embedding provider: openai, watsonx, or ollama",
            },
            "embedding_model": {
                "type": "string",
                "description": "Embedding model name",
            },
            "chunk_size": {
                "type": "integer",
                "description": "Chunk size for document ingestion",
            },
            "chunk_overlap": {
                "type": "integer",
                "description": "Chunk overlap for document ingestion",
            },
            "system_prompt": {
                "type": "string",
                "description": "System prompt for the agent",
            },
            "table_structure": {
                "type": "boolean",
                "description": "Enable table structure extraction in documents",
            },
            "ocr": {
                "type": "boolean",
                "description": "Enable OCR for images in documents",
            },
            "picture_descriptions": {
                "type": "boolean",
                "description": "Enable picture/image descriptions",
            },
        },
    },
)


async def handle_update_settings(arguments: dict) -> list[TextContent]:
    """Handle openrag_update_settings tool calls."""
    options = {k: v for k, v in arguments.items() if v is not None}
    if not options:
        return [TextContent(type="text", text="No settings to update. Provide at least one option.")]

    try:
        response = await _request_post("/api/v1/settings", "/v1/settings", options)
        if response.status_code != 200:
            return [TextContent(type="text", text=_format_http_error(response))]
        data = response.json()
        message = data.get("message", "Configuration updated successfully")
        return [TextContent(type="text", text=message)]
    except Exception as e:
        logger.error("Update settings error: %s", e)
        return [TextContent(type="text", text=f"Error updating settings: {str(e)}")]


# ============================================================================
# Tool: openrag_list_models
# ============================================================================

LIST_MODELS_TOOL = Tool(
    name="openrag_list_models",
    description=(
        "List available language models and embedding models for a provider. "
        "Use this before updating settings to see which model values are valid. "
        "Provider must be configured in OpenRAG (API key or endpoint set in Settings)."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "provider": {
                "type": "string",
                "description": "Provider to list models for: openai, anthropic, ollama, or watsonx",
                "enum": list(VALID_PROVIDERS),
            },
        },
        "required": ["provider"],
    },
)


async def handle_list_models(arguments: dict) -> list[TextContent]:
    """Handle openrag_list_models tool calls."""
    provider = (arguments.get("provider") or "").lower()
    if not provider:
        return [TextContent(type="text", text="Error: provider is required")]
    if provider not in VALID_PROVIDERS:
        return [
            TextContent(
                type="text",
                text=f"Error: provider must be one of {', '.join(VALID_PROVIDERS)}",
            )
        ]

    try:
        response = await _request_get(f"/api/v1/models/{provider}", f"/v1/models/{provider}")
        if response.status_code != 200:
            return [TextContent(type="text", text=_format_http_error(response))]

        data = response.json()
        language_models = data.get("language_models") or []
        embedding_models = data.get("embedding_models") or []

        parts = [f"**Available models for {provider}**\n"]
        parts.append("\n**Language models**")
        if language_models:
            for m in language_models:
                default = " (default)" if m.get("default") else ""
                parts.append(f"\n- {m.get('value', m.get('label', ''))}{default}")
        else:
            parts.append("\n- None")
        parts.append("\n**Embedding models**")
        if embedding_models:
            for m in embedding_models:
                default = " (default)" if m.get("default") else ""
                parts.append(f"\n- {m.get('value', m.get('label', ''))}{default}")
        else:
            parts.append("\n- None")

        return [TextContent(type="text", text="".join(parts))]

    except AttributeError as e:
        if "models" in str(e) and "OpenRAGClient" in str(e):
            msg = (
                "You're running an old build of openrag-mcp. To fix:\n"
                "1. Uninstall: uv pip uninstall openrag-mcp\n"
                "2. In Cursor MCP config (~/.cursor/mcp.json) use: \"args\": [\"run\", \"--directory\", \"/Users/edwin.jose/Documents/openrag/sdks/mcp\", \"openrag-mcp\"]\n"
                "3. Restart Cursor."
            )
            return [TextContent(type="text", text=msg)]
        raise
    except Exception as e:
        logger.error("List models error: %s", e)
        return [TextContent(type="text", text=f"Error listing models: {str(e)}")]


# ============================================================================
# Register all tools
# ============================================================================

register_tool(GET_SETTINGS_TOOL, handle_get_settings)
register_tool(UPDATE_SETTINGS_TOOL, handle_update_settings)
register_tool(LIST_MODELS_TOOL, handle_list_models)
