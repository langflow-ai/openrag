"""Models API should return sanitized provider error messages."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.responses import JSONResponse

from api import models as models_api


@pytest.mark.asyncio
async def test_get_ibm_models_returns_sanitized_provider_error():
    raw = (
        '{"errorCode":"BXNIM0415E",'
        '"errorMessage":"Provided API key could not be found.",'
        '"context":{"requestId":"abc"}}'
    )
    models_service = SimpleNamespace(
        get_ibm_models=AsyncMock(side_effect=Exception(raw)),
    )

    response = await models_api.get_ibm_models(
        body=models_api.IBMBody(
            api_key="bad-key",
            endpoint="https://ca-tor.ml.cloud.ibm.com",
            project_id="proj",
        ),
        models_service=models_service,
        user=SimpleNamespace(),
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    payload = json.loads(response.body)
    assert payload["error"] == "Provided API key is Invalid."


@pytest.mark.asyncio
async def test_get_openai_models_returns_sanitized_provider_error():
    raw = json.dumps(
        {
            "error": {
                "message": "Incorrect API key provided: sk-bad.",
                "type": "invalid_request_error",
                "code": "invalid_api_key",
            }
        }
    )
    models_service = SimpleNamespace(
        get_openai_models=AsyncMock(side_effect=Exception(raw)),
    )

    response = await models_api.get_openai_models(
        body=models_api.OpenAIBody(api_key="sk-bad"),
        models_service=models_service,
        user=SimpleNamespace(),
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    payload = json.loads(response.body)
    assert payload["error"] == "Incorrect API key provided: [REDACTED]."
    assert "sk-bad" not in payload["error"]


@pytest.mark.asyncio
async def test_get_openai_models_returns_502_on_transport_error():
    import httpx

    models_service = SimpleNamespace(
        get_openai_models=AsyncMock(
            side_effect=httpx.ConnectError("All connection attempts failed")
        ),
    )

    response = await models_api.get_openai_models(
        body=models_api.OpenAIBody(api_key="sk-test"),
        models_service=models_service,
        user=SimpleNamespace(),
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 502
    payload = json.loads(response.body)
    assert payload["error"] == "Unable to reach the model provider. Please try again."
    assert "connection attempts" not in payload["error"].lower()


@pytest.mark.asyncio
async def test_get_openai_models_returns_500_on_unexpected_error():
    models_service = SimpleNamespace(
        get_openai_models=AsyncMock(side_effect=RuntimeError("boom secret-key")),
    )

    response = await models_api.get_openai_models(
        body=models_api.OpenAIBody(api_key="sk-test"),
        models_service=models_service,
        user=SimpleNamespace(),
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500
    payload = json.loads(response.body)
    assert payload["error"] == "An unexpected error occurred while fetching models."
    assert "boom" not in payload["error"]


@pytest.mark.asyncio
async def test_get_ibm_models_returns_project_configuration_error():
    """Bare Exception from models_service is the user-facing contract — do not 500."""
    msg = (
        "API key is valid, but no models are available. "
        "This usually means your Watson Machine Learning (WML) project is not properly configured."
    )
    models_service = SimpleNamespace(
        get_ibm_models=AsyncMock(side_effect=Exception(msg)),
    )

    response = await models_api.get_ibm_models(
        body=models_api.IBMBody(
            api_key="ok-key",
            endpoint="https://ca-tor.ml.cloud.ibm.com",
            project_id="proj",
        ),
        models_service=models_service,
        user=SimpleNamespace(),
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    payload = json.loads(response.body)
    assert payload["error"] == msg


@pytest.mark.asyncio
async def test_get_model_catalog_returns_only_supported_providers():
    response = await models_api.get_model_catalog(user=SimpleNamespace())
    assert isinstance(response, JSONResponse)
    assert response.status_code == 200
    payload = json.loads(response.body)
    keys = {provider["key"] for provider in payload["providers"]}
    assert keys == {"openai", "anthropic", "ollama", "watsonx"}
    openai = next(p for p in payload["providers"] if p["key"] == "openai")
    assert openai["models"]
    assert openai["embedding_models"]
    cache_control = response.headers.get("cache-control") or response.headers.get("Cache-Control")
    assert cache_control == "private, max-age=3600"
