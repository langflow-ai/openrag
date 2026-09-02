"""OpenAI-compatible LLM proxy for Langflow and other OpenAI clients.

Auth is a short-lived Langflow hop token (same family as ingest tokens),
the user JWT, or an `orag_` API key. Provider secrets stay in BomaRAG.
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
    try:
        return JSONResponse(catalog(), headers={"Cache-Control": "private, max-age=3600"})
    except CatalogUnavailableError as exc:
        logger.error("Model catalogue unavailable", error=str(exc))
        return JSONResponse({"error": CATALOG_UNAVAILABLE_MESSAGE}, status_code=503)


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
