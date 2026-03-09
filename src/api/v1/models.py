"""
Public API v1 Models endpoint.

Lists available LLM and embedding models per provider.
Uses API key authentication. Uses stored credentials from config.
"""
from fastapi import Depends
from fastapi.responses import JSONResponse
from config.settings import get_openrag_config
from utils.logging_config import get_logger
from dependencies import get_models_service, get_api_key_user_async
from session_manager import User

logger = get_logger(__name__)

VALID_PROVIDERS = frozenset({"openai", "anthropic", "ollama", "watsonx"})


async def _fetch_models(provider, config, models_service):
    """Fetch models for the given provider using config credentials."""
    if provider == "openai":
        api_key = config.providers.openai.api_key
        if not api_key:
            return None, JSONResponse({"error": "OpenAI API key not configured. Set it in Settings."}, status_code=400)
        models = await models_service.get_openai_models(api_key=api_key)
        return models, None

    if provider == "anthropic":
        api_key = config.providers.anthropic.api_key
        if not api_key:
            return None, JSONResponse({"error": "Anthropic API key not configured. Set it in Settings."}, status_code=400)
        models = await models_service.get_anthropic_models(api_key=api_key)
        return models, None

    if provider == "ollama":
        endpoint = config.providers.ollama.endpoint
        if not endpoint:
            return None, JSONResponse({"error": "Ollama endpoint not configured. Set it in Settings."}, status_code=400)
        models = await models_service.get_ollama_models(endpoint=endpoint)
        return models, None

    # watsonx
    api_key = config.providers.watsonx.api_key
    endpoint = config.providers.watsonx.endpoint
    project_id = config.providers.watsonx.project_id
    if not api_key:
        return None, JSONResponse({"error": "WatsonX API key not configured. Set it in Settings."}, status_code=400)
    if not endpoint:
        return None, JSONResponse({"error": "WatsonX endpoint not configured. Set it in Settings."}, status_code=400)
    if not project_id:
        return None, JSONResponse({"error": "WatsonX project ID not configured. Set it in Settings."}, status_code=400)
    models = await models_service.get_ibm_models(endpoint=endpoint, api_key=api_key, project_id=project_id)
    return models, None


async def list_models_endpoint(
    provider: str,
    models_service=Depends(get_models_service),
    user: User = Depends(get_api_key_user_async),
):
    """
    List available language and embedding models for a provider.

    GET /v1/models/{provider}
    """
    provider = provider.lower()
    if provider not in VALID_PROVIDERS:
        return JSONResponse(
            {"error": f"Invalid provider. Must be one of: {', '.join(sorted(VALID_PROVIDERS))}"},
            status_code=400,
        )

    try:
        config = get_openrag_config()
        models, error_response = await _fetch_models(provider, config, models_service)
        if error_response is not None:
            return error_response
        return JSONResponse(models)
    except Exception as e:
        logger.error("Failed to list models for provider %s: %s", provider, str(e))
        return JSONResponse({"error": f"Failed to retrieve models: {str(e)}"}, status_code=500)
