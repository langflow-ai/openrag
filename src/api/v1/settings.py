"""
Public API v1 Settings endpoint.

Provides access to configuration settings.
Uses API key authentication.
"""
from starlette.requests import Request
from starlette.responses import JSONResponse
from utils.logging_config import get_logger
from config.settings import get_openrag_config

logger = get_logger(__name__)


async def get_settings_endpoint(request: Request):
    """
    Get current OpenRAG configuration (read-only).

    GET /v1/settings

    Response:
        {
            "agent": {
                "llm_provider": "openai",
                "llm_model": "gpt-4"
            },
            "knowledge": {
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-3-small"
            }
        }

    Note: This endpoint returns a limited subset of settings.
    Sensitive information (API keys, credentials) is never exposed.
    """
    try:
        from config.settings import get_openrag_config

        config = get_openrag_config()

        # Return only safe, non-sensitive settings
        settings = {
            "agent": {
                "llm_provider": config.agent.llm_provider,
                "llm_model": config.agent.llm_model,
            },
            "knowledge": {
                "embedding_provider": config.knowledge.embedding_provider,
                "embedding_model": config.knowledge.embedding_model,
                "chunk_size": config.knowledge.chunk_size,
                "chunk_overlap": config.knowledge.chunk_overlap,
            },
        }

        return JSONResponse(settings)

    except Exception as e:
        logger.error("Failed to get settings", error=str(e))
        return JSONResponse(
            {"error": "Failed to get settings"},
            status_code=500,
        )


async def update_settings_endpoint(request: Request, session_manager):
    """
    Update OpenRAG configuration settings.

    POST /v1/settings

    Request body (all fields optional):
        {
            "chunk_size": 1000,
            "chunk_overlap": 200
        }

    Response:
        {
            "message": "Configuration updated successfully"
        }

    Note: This endpoint only allows updating a limited subset of settings.
    Provider API keys and credentials cannot be updated via this endpoint.
    """
    from api.settings import update_settings
    return await update_settings(request, session_manager)
