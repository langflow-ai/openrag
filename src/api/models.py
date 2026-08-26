import re

import httpx
from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.provider_validation import (
    is_provider_credential_error,
    sanitize_provider_error_content,
)
from config.settings import get_openrag_config
from dependencies import get_models_service, require_permission
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)

_CREDENTIAL_PATTERNS = (
    # OpenAI / Anthropic / Langflow-style secret prefixes echoed by providers.
    re.compile(r"\bsk-(?:ant-|lf-)?[A-Za-z0-9_\-]{3,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|apikey|x-api-key)\s*[:=]\s*['\"]?[^\s'\",}]+"),
)


def _redact_credentials(message: str) -> str:
    """Strip provider-echoed secrets before returning errors to clients."""
    redacted = message
    for pattern in _CREDENTIAL_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class OpenAIBody(BaseModel):
    api_key: str | None = None


class AnthropicBody(BaseModel):
    api_key: str | None = None


class IBMBody(BaseModel):
    api_key: str | None = None
    endpoint: str | None = None
    project_id: str | None = None


def _models_error_response(exc: Exception) -> JSONResponse:
    """Map model-route failures to client (400) vs upstream (502) vs server (500).

    ``models_service`` raises bare ``Exception(user_message)`` for actionable
    provider/config failures (invalid key, empty model list, bad project). Those
    must reach onboarding as sanitized text. Unexpected internals (e.g.
    ``RuntimeError``) stay behind the generic 500.
    """
    if isinstance(exc, (httpx.TimeoutException, httpx.RequestError)):
        return JSONResponse(
            {"error": "Unable to reach the model provider. Please try again."},
            status_code=502,
        )

    error = sanitize_provider_error_content(exc)
    redacted = _redact_credentials(error)
    if is_provider_credential_error(exc) or is_provider_credential_error(error):
        return JSONResponse({"error": redacted}, status_code=400)
    if isinstance(exc, (ValueError, TypeError)) or type(exc) is Exception:
        # Bare Exception is the models_service user-facing contract; keep JSON
        # / traceback leaks behind the generic response.
        if redacted and "{" not in redacted and "}" not in redacted:
            return JSONResponse({"error": redacted}, status_code=400)
    return JSONResponse(
        {"error": "An unexpected error occurred while fetching models."},
        status_code=500,
    )


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
        return _models_error_response(e)


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
        return _models_error_response(e)


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
        return _models_error_response(e)


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
        return _models_error_response(e)


async def get_model_providers(
    user: User = Depends(require_permission("providers:read")),
):
    """Providers this run mode exposes. GET /models/providers

    The one list Settings cards, Onboarding tabs and the model pickers render.
    Unlike /models/catalog it does not need LiteLLM, so the UI can still lay out
    its provider surfaces when the catalogue is unavailable.
    """
    from config.model_providers import provider_visibility_payload

    return JSONResponse(
        provider_visibility_payload(),
        headers={"Cache-Control": "private, max-age=300"},
    )


async def get_model_catalog(
    user: User = Depends(require_permission("providers:read")),
):
    """LiteLLM catalogue for the settings model dropdown. GET /models/catalog"""
    from services.model_catalog import (
        CATALOG_UNAVAILABLE_MESSAGE,
        CatalogUnavailableError,
        catalog,
    )

    try:
        return JSONResponse(catalog(), headers={"Cache-Control": "private, max-age=3600"})
    except CatalogUnavailableError as e:
        # Log the cause, but never echo exception text back to the caller
        # (CodeQL py/stack-trace-exposure).
        logger.error("Model catalogue unavailable", error=str(e))
        return JSONResponse({"error": CATALOG_UNAVAILABLE_MESSAGE}, status_code=503)
