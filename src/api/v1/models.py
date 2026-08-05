"""
Public API v1 Models endpoint.

Lists available LLM and embedding models per provider.
Uses API key authentication. Uses stored credentials from config.
"""

from fastapi import Depends
from fastapi.responses import JSONResponse

from config.settings import get_openrag_config
from dependencies import get_models_service, require_api_key_permission
from services.model_catalog import catalog, is_known_provider
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def _fetch_models(provider, config, models_service):
    """Fetch models for the given provider using config credentials."""
    if provider == "openai":
        api_key = config.providers.openai.api_key
        if not api_key:
            return None, JSONResponse(
                {"error": "OpenAI API key not configured. Set it in Settings."}, status_code=400
            )
        models = await models_service.get_openai_models(
            api_key=api_key, base_url=config.providers.openai.base_url or None
        )
        return models, None

    if provider == "anthropic":
        api_key = config.providers.anthropic.api_key
        if not api_key:
            return None, JSONResponse(
                {"error": "Anthropic API key not configured. Set it in Settings."}, status_code=400
            )
        models = await models_service.get_anthropic_models(api_key=api_key)
        return models, None

    if provider == "ollama":
        endpoint = config.providers.ollama.endpoint
        if not endpoint:
            return None, JSONResponse(
                {"error": "Ollama endpoint not configured. Set it in Settings."}, status_code=400
            )
        models = await models_service.get_ollama_models(endpoint=endpoint)
        return models, None

    if provider == "watsonx":
        api_key = config.providers.watsonx.api_key
        endpoint = config.providers.watsonx.endpoint
        project_id = config.providers.watsonx.project_id
        if not api_key:
            return None, JSONResponse(
                {"error": "WatsonX API key not configured. Set it in Settings."},
                status_code=400,
            )
        if not endpoint:
            return None, JSONResponse(
                {"error": "WatsonX endpoint not configured. Set it in Settings."},
                status_code=400,
            )
        if not project_id:
            return None, JSONResponse(
                {"error": "WatsonX project ID not configured. Set it in Settings."},
                status_code=400,
            )
        models = await models_service.get_ibm_models(
            endpoint=endpoint, api_key=api_key, project_id=project_id
        )
        return models, None

    provider_config = config.providers.get_provider_config(provider)
    if not provider_config.configured:
        return None, JSONResponse(
            {"error": f"{provider} is not configured. Set it in Settings."},
            status_code=400,
        )
    entry = next(
        (item for item in catalog()["providers"] if item["key"] == provider),
        None,
    )
    if entry is None:
        return {"language_models": [], "embedding_models": []}, None
    return {
        "language_models": [
            {
                "value": model["model"],
                "label": model["model"],
                "default": False,
                "supports_images": "vision" in model.get("capabilities", []),
            }
            for model in entry["models"]
        ],
        "embedding_models": [
            {
                "value": model["model"],
                "label": model["model"],
                "default": False,
            }
            for model in entry["embedding_models"]
        ],
    }, None


async def list_models_endpoint(
    provider: str,
    models_service=Depends(get_models_service),
    user: User = Depends(require_api_key_permission("providers:read")),
):
    """
    List available language and embedding models for a provider.

    GET /v1/models/{provider}
    """
    provider = provider.lower()
    if not is_known_provider(provider):
        return JSONResponse(
            {"error": f"Unknown LiteLLM provider: {provider}"},
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
