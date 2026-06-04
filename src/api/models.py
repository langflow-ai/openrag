from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config.settings import get_openrag_config
from dependencies import get_models_service, require_permission
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


class OpenAIBody(BaseModel):
    api_key: str | None = None


class AnthropicBody(BaseModel):
    api_key: str | None = None


class IBMBody(BaseModel):
    api_key: str | None = None
    endpoint: str | None = None
    project_id: str | None = None


async def get_openai_models(
    body: OpenAIBody | None = None,
    models_service=Depends(get_models_service),
    user: User = Depends(require_permission("providers:read")),
):
    """Get available OpenAI models"""
    try:
        api_key = body.api_key if body else None
        if not api_key:
            try:
                config = get_openrag_config()
                api_key = config.providers.openai.api_key
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not api_key:
            return JSONResponse(
                {"error": "OpenAI API key is required either in request body or in configuration"},
                status_code=400,
            )

        models = await models_service.get_openai_models(api_key=api_key)
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get OpenAI models: {str(e)}")
        return JSONResponse({"error": "Failed to retrieve OpenAI models"}, status_code=500)


async def get_anthropic_models(
    body: AnthropicBody | None = None,
    models_service=Depends(get_models_service),
    user: User = Depends(require_permission("providers:read")),
):
    """Get available Anthropic models"""
    try:
        api_key = body.api_key if body else None
        if not api_key:
            try:
                config = get_openrag_config()
                api_key = config.providers.anthropic.api_key
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not api_key:
            return JSONResponse(
                {
                    "error": "Anthropic API key is required either in request body or in configuration"
                },
                status_code=400,
            )

        models = await models_service.get_anthropic_models(api_key=api_key)
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get Anthropic models: {str(e)}")
        return JSONResponse({"error": "Failed to retrieve Anthropic models"}, status_code=500)


async def get_ollama_models(
    endpoint: str | None = None,
    models_service=Depends(get_models_service),
    user: User = Depends(require_permission("providers:read")),
):
    """Get available Ollama models"""
    try:
        if not endpoint:
            try:
                config = get_openrag_config()
                endpoint = config.providers.ollama.endpoint
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not endpoint:
            return JSONResponse(
                {"error": "Endpoint is required either as query parameter or in configuration"},
                status_code=400,
            )

        models = await models_service.get_ollama_models(endpoint=endpoint)
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get Ollama models: {str(e)}")
        return JSONResponse({"error": "Failed to retrieve Ollama models"}, status_code=500)


async def get_ibm_models(
    body: IBMBody | None = None,
    models_service=Depends(get_models_service),
    user: User = Depends(require_permission("providers:read")),
):
    """Get available IBM Watson models"""
    try:
        api_key = body.api_key if body else None
        endpoint = body.endpoint if body else None
        project_id = body.project_id if body else None

        config = get_openrag_config()
        if not api_key:
            try:
                api_key = config.providers.watsonx.api_key
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not api_key:
            return JSONResponse(
                {"error": "WatsonX API key is required either in request body or in configuration"},
                status_code=400,
            )

        if not endpoint:
            try:
                endpoint = config.providers.watsonx.endpoint
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not endpoint:
            return JSONResponse(
                {"error": "Endpoint is required either in request body or in configuration"},
                status_code=400,
            )

        if not project_id:
            try:
                project_id = config.providers.watsonx.project_id
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not project_id:
            return JSONResponse(
                {"error": "Project ID is required either in request body or in configuration"},
                status_code=400,
            )

        models = await models_service.get_ibm_models(
            endpoint=endpoint, api_key=api_key, project_id=project_id
        )
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get IBM models: {str(e)}")
        return JSONResponse({"error": "Failed to retrieve IBM models"}, status_code=500)
