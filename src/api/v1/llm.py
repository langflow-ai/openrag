"""OpenAI-compatible LLM proxy for Langflow and other OpenAI clients.

Auth is a short-lived Langflow hop token (same family as ingest tokens),
the user JWT, or an `orag_` API key. Provider secrets stay in OpenRAG.
"""

from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from dependencies import require_llm_proxy_any_permission, require_llm_proxy_permission
from services.llm_gateway import LlmGatewayError, chat_completions, embeddings
from services.model_catalog import (
    CATALOG_UNAVAILABLE_MESSAGE,
    CatalogUnavailableError,
    catalog,
    openai_models_list,
)
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)

_catalog_read = require_llm_proxy_any_permission(("providers:read", "chat:use", "knowledge:upload"))
_embeddings_use = require_llm_proxy_any_permission(("chat:use", "knowledge:upload"))
_chat_use = require_llm_proxy_permission("chat:use")


def _openai_error(message: str, status_code: int, error_type: str = "invalid_request_error"):
    return JSONResponse(
        {"error": {"message": message, "type": error_type}},
        status_code=status_code,
    )


def _gateway_error(exc: LlmGatewayError):
    error_type = "invalid_request_error" if exc.status_code < 500 else "api_error"
    if exc.detail != exc.message:
        logger.error("LLM gateway error", status_code=exc.status_code, error=exc.detail)
    return _openai_error(exc.message, exc.status_code, error_type)


async def list_openai_models_endpoint(
    user: User = Depends(_catalog_read),
):
    """OpenAI-compatible model inventory. GET /v1/models"""
    try:
        return JSONResponse(openai_models_list())
    except CatalogUnavailableError as exc:
        # Log the cause, but never echo exception text back to the caller
        # (CodeQL py/stack-trace-exposure).
        logger.error("Model catalogue unavailable", error=str(exc))
        return _openai_error(CATALOG_UNAVAILABLE_MESSAGE, 503, "api_error")


async def model_catalog_endpoint(
    user: User = Depends(_catalog_read),
):
    """LiteLLM picker payload. GET /v1/model-catalog"""
    # `no-store` for the same reason as /models/providers: the catalogue is
    # filtered by that config file, so a cached copy survives the restart that
    # was supposed to apply the edit. LiteLLM's table is cached in-process, so
    # rebuilding this response is cheap.
    try:
        return JSONResponse(catalog(), headers={"Cache-Control": "no-store"})
    except CatalogUnavailableError as exc:
        logger.error("Model catalogue unavailable", error=str(exc))
        return JSONResponse({"error": CATALOG_UNAVAILABLE_MESSAGE}, status_code=503)


async def model_providers_endpoint(
    user: User = Depends(_catalog_read),
):
    """Providers this run mode exposes. GET /v1/model-providers

    Same list the console reads from /models/providers, so an SDK client and the
    UI never disagree about which providers a deployment offers.
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


async def _read_json_body(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return _openai_error("Request body must be valid JSON", 400)
    if not isinstance(body, dict):
        return _openai_error("Request body must be a JSON object", 400)
    return body


async def chat_completions_endpoint(
    request: Request,
    user: User = Depends(_chat_use),
):
    """OpenAI-compatible chat completions. POST /v1/chat/completions"""
    body = await _read_json_body(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        result = await chat_completions(body)
    except LlmGatewayError as exc:
        return _gateway_error(exc)
    if body.get("stream"):
        return StreamingResponse(
            result,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    return JSONResponse(result)


async def embeddings_endpoint(
    request: Request,
    user: User = Depends(_embeddings_use),
):
    """OpenAI-compatible embeddings. POST /v1/embeddings"""
    body = await _read_json_body(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        result = await embeddings(body)
    except LlmGatewayError as exc:
        return _gateway_error(exc)
    return JSONResponse(result)
