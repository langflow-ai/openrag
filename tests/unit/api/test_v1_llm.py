"""OpenAI-compatible /v1 LLM proxy handlers."""

import inspect
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import params as fastapi_params
from fastapi.responses import JSONResponse, StreamingResponse

from api.v1 import llm as v1_llm
from services.llm_gateway import LlmGatewayError
from services.model_catalog import CATALOG_UNAVAILABLE_MESSAGE, CatalogUnavailableError
from session_manager import User


def _user() -> User:
    return User(user_id="u1", email="u@x", name="U", provider="api_key")


def _get_user_dependency(fn):
    user_param = inspect.signature(fn).parameters["user"]
    default = user_param.default
    assert isinstance(default, fastapi_params.Depends)
    return default.dependency


def test_completions_requires_chat_use():
    dep = _get_user_dependency(v1_llm.chat_completions_endpoint)
    perms = [cell.cell_contents for cell in dep.__closure__]
    assert "chat:use" in perms


def test_embeddings_accepts_chat_or_upload():
    dep = _get_user_dependency(v1_llm.embeddings_endpoint)
    required = [cell.cell_contents for cell in dep.__closure__]
    assert any("chat:use" in str(item) or "knowledge:upload" in str(item) for item in required)


@pytest.mark.asyncio
async def test_list_openai_models_returns_openai_list():
    response = await v1_llm.list_openai_models_endpoint(user=_user())
    assert isinstance(response, JSONResponse)
    data = json.loads(response.body)
    assert data["object"] == "list"
    assert data["data"]
    assert data["data"][0]["object"] == "model"


@pytest.mark.asyncio
async def test_model_catalog_returns_providers():
    response = await v1_llm.model_catalog_endpoint(user=_user())
    data = json.loads(response.body)
    keys = {p["key"] for p in data["providers"]}
    assert "openai" in keys
    assert "anthropic" in keys
    openai = next(p for p in data["providers"] if p["key"] == "openai")
    assert openai["models"]
    assert openai["embedding_models"]
    assert openai["credential_fields"]


@pytest.mark.asyncio
async def test_chat_completions_delegates_to_gateway(monkeypatch):
    monkeypatch.setattr(
        v1_llm,
        "chat_completions",
        AsyncMock(
            return_value={
                "id": "chatcmpl-1",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            }
        ),
    )
    request = MagicMock()
    request.json = AsyncMock(
        return_value={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}
    )
    response = await v1_llm.chat_completions_endpoint(request, user=_user())
    data = json.loads(response.body)
    assert data["choices"][0]["message"]["content"] == "ok"


@pytest.mark.asyncio
async def test_chat_completions_streams(monkeypatch):
    async def fake_stream():
        yield 'data: {"choices":[]}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(v1_llm, "chat_completions", AsyncMock(return_value=fake_stream()))
    request = MagicMock()
    request.json = AsyncMock(return_value={"model": "gpt-4o-mini", "messages": [], "stream": True})
    response = await v1_llm.chat_completions_endpoint(request, user=_user())
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_chat_completions_maps_gateway_errors(monkeypatch):
    monkeypatch.setattr(
        v1_llm,
        "chat_completions",
        AsyncMock(side_effect=LlmGatewayError("OpenAI API key is not configured", 400)),
    )
    request = MagicMock()
    request.json = AsyncMock(return_value={"model": "gpt-4o-mini", "messages": []})
    response = await v1_llm.chat_completions_endpoint(request, user=_user())
    assert response.status_code == 400
    data = json.loads(response.body)
    assert data["error"]["message"] == "OpenAI API key is not configured"


@pytest.mark.asyncio
async def test_embeddings_delegates_to_gateway(monkeypatch):
    monkeypatch.setattr(
        v1_llm,
        "embeddings",
        AsyncMock(return_value={"object": "list", "data": [{"embedding": [0.2]}]}),
    )
    request = MagicMock()
    request.json = AsyncMock(return_value={"model": "text-embedding-3-small", "input": ["x"]})
    response = await v1_llm.embeddings_endpoint(request, user=_user())
    data = json.loads(response.body)
    assert data["data"][0]["embedding"] == [0.2]


@pytest.mark.asyncio
async def test_list_openai_models_hides_catalog_exception_text(monkeypatch):
    """CodeQL py/stack-trace-exposure: the exception text must not reach the caller."""
    monkeypatch.setattr(
        v1_llm,
        "openai_models_list",
        MagicMock(side_effect=CatalogUnavailableError("litellm is not installed on the server")),
    )
    response = await v1_llm.list_openai_models_endpoint(user=_user())
    assert response.status_code == 503
    data = json.loads(response.body)
    assert data["error"]["message"] == CATALOG_UNAVAILABLE_MESSAGE
    assert "litellm" not in response.body.decode()


@pytest.mark.asyncio
async def test_model_catalog_hides_catalog_exception_text(monkeypatch):
    monkeypatch.setattr(
        v1_llm,
        "catalog",
        MagicMock(side_effect=CatalogUnavailableError("litellm is not installed on the server")),
    )
    response = await v1_llm.model_catalog_endpoint(user=_user())
    assert response.status_code == 503
    data = json.loads(response.body)
    assert data["error"] == CATALOG_UNAVAILABLE_MESSAGE
    assert "litellm" not in response.body.decode()


@pytest.mark.asyncio
async def test_gateway_error_detail_is_not_returned_to_the_caller(monkeypatch):
    """`detail` is log-only; only the sanitized `message` is serialized."""
    monkeypatch.setattr(
        v1_llm,
        "chat_completions",
        AsyncMock(
            side_effect=LlmGatewayError(
                "The model provider could not be reached. Please try again.",
                502,
                detail="RuntimeError: connect to 10.0.0.5 failed",
            )
        ),
    )
    request = MagicMock()
    request.json = AsyncMock(return_value={"model": "gpt-4o-mini", "messages": []})
    response = await v1_llm.chat_completions_endpoint(request, user=_user())

    assert response.status_code == 502
    body = response.body.decode()
    assert "10.0.0.5" not in body
    assert "RuntimeError" not in body
    assert json.loads(body)["error"]["type"] == "api_error"
