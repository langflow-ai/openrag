from typing import Optional

from fastapi import Depends
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from utils.logging_config import get_logger
from config.settings import get_openrag_config
from dependencies import get_models_service, get_current_user
from session_manager import User

logger = get_logger(__name__)


class OpenAIBody(BaseModel):
    api_key: Optional[str] = None


class AnthropicBody(BaseModel):
    api_key: Optional[str] = None


class IBMBody(BaseModel):
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    project_id: Optional[str] = None


async def get_openai_models(
    body: Optional[OpenAIBody] = None,
    models_service=Depends(get_models_service),
    user: User = Depends(get_current_user),
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
        return JSONResponse({"error": f"Failed to retrieve OpenAI models: {str(e)}"}, status_code=500)


async def get_anthropic_models(
    body: Optional[AnthropicBody] = None,
    models_service=Depends(get_models_service),
    user: User = Depends(get_current_user),
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
                {"error": "Anthropic API key is required either in request body or in configuration"},
                status_code=400,
            )

        models = await models_service.get_anthropic_models(api_key=api_key)
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get Anthropic models: {str(e)}")
        return JSONResponse({"error": f"Failed to retrieve Anthropic models: {str(e)}"}, status_code=500)


async def get_ollama_models(
    endpoint: Optional[str] = None,
    models_service=Depends(get_models_service),
    user: User = Depends(get_current_user),
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
        return JSONResponse({"error": f"Failed to retrieve Ollama models: {str(e)}"}, status_code=500)


async def get_ibm_models(
    body: Optional[IBMBody] = None,
    models_service=Depends(get_models_service),
    user: User = Depends(get_current_user),
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
        return JSONResponse({"error": f"Failed to retrieve IBM models: {str(e)}"}, status_code=500)
