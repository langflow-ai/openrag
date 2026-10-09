import re
from collections.abc import Mapping
from types import ModuleType
from typing import Any

import httpx
from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.provider_validation import (
    is_provider_credential_error,
    sanitize_provider_error_content,
)
from config.settings import get_openrag_config
from dependencies import get_models_service, require_permission
from services.model_catalog import hide_excluded_live_models
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


class WatsonxOnPremSpacesBody(BaseModel):
    credentials: dict[str, str] = Field(default_factory=dict)
    auth_method: str | None = None


class ModelDiscoveryBody(BaseModel):
    credentials: dict[str, str] = Field(default_factory=dict)
    auth_method: str | None = None


#: Fields that say *where* credentials are sent. When a form changes one, the
#: stored values belong to a different host and must not travel with it.
_CREDENTIAL_TARGET_FIELDS = ("api_base", "embedding_api_base", "ssl_verify")


class InvalidAuthMethodError(ValueError):
    """The form named an auth method its provider does not offer — a client error."""


def _draft_credentials(
    enhancement: ModuleType, submitted: Mapping[str, str], auth_method: str | None
) -> dict[str, Any]:
    """Credentials a form has typed, completed from the stored ones where safe.

    A secret the operator saved earlier is shown blank in the form, so the
    stored value fills in whatever was not typed — but only while the form still
    points at the same host. A changed endpoint or TLS setting drops every
    stored value, so a saved token is never sent somewhere it was not saved for.
    Only the fields the provider's form defines (for the chosen auth method,
    where it has several) are kept.

    Raises `InvalidAuthMethodError` when the provider rejects `auth_method`.
    """
    from enhancements.providers.registry import default_auth_method_for

    config = get_openrag_config()
    stored = config.providers.stored_credentials(enhancement.PROVIDER_KEY)
    fields_for_auth_method = getattr(enhancement, "credential_fields_for_auth_method", None)
    if callable(fields_for_auth_method):
        stored_config = config.providers.get_provider_config(enhancement.PROVIDER_KEY)
        method = (
            auth_method
            or getattr(stored_config, "auth_method", None)
            or default_auth_method_for(enhancement.PROVIDER_KEY, stored)
        )
        if not method:
            raise InvalidAuthMethodError("Choose an authentication method.")
        try:
            allowed = set(fields_for_auth_method(method))
        except ValueError as exc:
            raise InvalidAuthMethodError(str(exc)) from exc
    else:
        allowed = {str(field["key"]) for field in enhancement.CREDENTIAL_FIELDS}
    typed = {
        name: str(value).strip()
        for name, value in submitted.items()
        if name in allowed and str(value).strip()
    }
    target_changed = any(
        name in typed and typed[name] != stored.get(name) for name in _CREDENTIAL_TARGET_FIELDS
    )
    base = {} if target_changed else stored
    return {name: value for name, value in {**base, **typed}.items() if name in allowed}


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
        return JSONResponse(hide_excluded_live_models("openai", models))
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
        return JSONResponse(hide_excluded_live_models("anthropic", models))
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
        return JSONResponse(hide_excluded_live_models("ollama", models))
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
        return JSONResponse(hide_excluded_live_models("watsonx", models))
    except Exception as e:
        logger.error(f"Failed to get IBM models: {str(e)}")
        return _models_error_response(e)


async def get_watsonx_onprem_spaces(
    body: WatsonxOnPremSpacesBody | None = None,
    user: User = Depends(require_permission("providers:write")),
):
    """Deployment spaces visible to the pending watsonx.ai on-prem credentials."""
    from enhancements.providers.watsonx import onprem

    request = body or WatsonxOnPremSpacesBody()
    try:
        credentials = _draft_credentials(onprem, request.credentials, request.auth_method)
        spaces = await onprem.list_spaces(credentials)
        return JSONResponse(
            {"spaces": spaces},
            headers={"Cache-Control": "no-store"},
        )
    except onprem.SpaceDiscoveryError as exc:
        logger.warning(
            "watsonx.ai on-prem space discovery was rejected",
            status_code=exc.status_code,
        )
        status_code = exc.status_code if exc.status_code in {400, 401, 403, 404} else 502
        if status_code in {401, 403}:
            error = "The cluster rejected the configured credentials."
        elif status_code == 404:
            error = "The cluster deployment-space endpoint was not found."
        elif status_code == 400:
            error = "The cluster rejected the deployment-space request."
        else:
            error = "Unable to list deployment spaces from the cluster."
        return JSONResponse({"error": error}, status_code=status_code)
    except InvalidAuthMethodError as exc:
        logger.warning("watsonx.ai on-prem space discovery named an unknown auth method")
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.error("Failed to list watsonx.ai on-prem spaces", exc_info=exc)
        return JSONResponse(
            {"error": "Unable to list deployment spaces from the cluster."},
            status_code=500,
        )


async def discover_provider_models(
    provider: str,
    body: ModelDiscoveryBody | None = None,
    user: User = Depends(require_permission("providers:write")),
):
    """Models a cluster serves, asked with credentials that may not be saved yet.

    POST /models/{provider}/discover. Onboarding calls this while the operator
    is still filling the form: the catalogue only lists a cluster with *saved*
    credentials, and a vLLM `--served-model-name` can be anything, so without it
    the picker offers the configured fallback rather than what is deployed.

    Each half is null when that endpoint could not be listed, and the caller
    keeps the catalogue's rows for it.
    """
    from enhancements.providers.registry import model_discovery_for
    from services.model_catalog import discovered_model_payload, supported_provider_keys

    key = (provider or "").strip().lower()
    enhancement = model_discovery_for(key)
    if enhancement is None or key not in supported_provider_keys():
        return JSONResponse(
            {"error": "This provider cannot list its models."},
            status_code=404,
        )
    request = body or ModelDiscoveryBody()
    try:
        credentials = _draft_credentials(enhancement, request.credentials, request.auth_method)
        listed = await enhancement.list_cluster_models(credentials)
        return JSONResponse(
            discovered_model_payload(key, listed),
            headers={"Cache-Control": "no-store"},
        )
    except InvalidAuthMethodError as exc:
        logger.warning("Model discovery named an unknown auth method", provider=key)
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.error("Failed to discover provider models", provider=key, exc_info=exc)
        return JSONResponse(
            {"error": "Unable to list models from the provider."},
            status_code=500,
        )


async def get_model_providers(
    user: User = Depends(require_permission("providers:read")),
):
    """Providers this run mode exposes. GET /models/providers

    The one list Settings cards, Onboarding tabs and the model pickers render.
    Unlike /models/catalog it does not need LiteLLM, so the UI can still lay out
    its provider surfaces when the catalogue is unavailable.
    """
    from config.model_providers import provider_visibility_payload

    # `no-store`, not a max-age: the list is derived from
    # `config/model_providers.yaml`, which an operator edits and then restarts
    # the backend for. A cached response outlives that restart in the browser,
    # so the console keeps drawing the old provider cards/tabs and the change
    # looks like it did nothing. The payload is a few hundred bytes and React
    # Query already holds it for the session, so the round trip costs nothing.
    return JSONResponse(
        provider_visibility_payload(),
        headers={"Cache-Control": "no-store"},
    )


async def get_model_catalog(
    user: User = Depends(require_permission("providers:read")),
):
    """LiteLLM catalogue for the settings model dropdown. GET /models/catalog"""
    from services.model_catalog import (
        CATALOG_UNAVAILABLE_MESSAGE,
        CatalogUnavailableError,
        catalog,
        refresh_live_models,
    )

    # `no-store` for the same reason as /models/providers: the catalogue is
    # filtered by that config file, so a cached copy survives the restart that
    # was supposed to apply the edit. LiteLLM's table is cached in-process, so
    # rebuilding this response is cheap.
    try:
        # A cluster-hosted provider is the only source for its own model list,
        # so ask it before building the payload the pickers read.
        await refresh_live_models()
        return JSONResponse(catalog(), headers={"Cache-Control": "no-store"})
    except CatalogUnavailableError as e:
        # Log the cause, but never echo exception text back to the caller
        # (CodeQL py/stack-trace-exposure).
        logger.error("Model catalogue unavailable", error=str(e))
        return JSONResponse({"error": CATALOG_UNAVAILABLE_MESSAGE}, status_code=503)
