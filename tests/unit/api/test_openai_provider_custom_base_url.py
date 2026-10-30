"""Regression coverage for OpenAI-compatible custom API base URLs."""

from types import SimpleNamespace

import pytest

from api import provider_validation
from services.models_service import ModelsService


@pytest.mark.asyncio
async def test_openai_lightweight_health_preserves_custom_base_path(monkeypatch):
    calls = []

    async def fake_request(method, url, **kwargs):
        calls.append((method, url))
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(provider_validation, "_http_request_with_retry", fake_request)

    await provider_validation.test_lightweight_health(
        "openai",
        api_key="test-key",
        credentials={"api_key": "test-key", "api_base": "https://gateway.example/openai"},
    )

    assert calls == [("GET", "https://gateway.example/openai/models")]


@pytest.mark.asyncio
async def test_openai_completion_and_embedding_use_custom_base(monkeypatch):
    calls = []

    async def fake_request(method, url, **kwargs):
        calls.append((method, url))
        if url.endswith("/embeddings"):
            return SimpleNamespace(status_code=200, json=lambda: {"data": [{"embedding": [0.1]}]})
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(provider_validation, "_http_request_with_retry", fake_request)

    await provider_validation.test_completion_with_tools(
        "openai",
        "test-key",
        "example-model",
        credentials={"api_key": "test-key", "api_base": "https://gateway.example/openai"},
    )
    await provider_validation.test_embedding(
        "openai",
        "test-key",
        "example-embedding",
        credentials={"api_key": "test-key", "api_base": "https://gateway.example/openai"},
    )

    assert calls == [
        ("POST", "https://gateway.example/openai/chat/completions"),
        ("POST", "https://gateway.example/openai/embeddings"),
    ]


@pytest.mark.asyncio
async def test_openai_model_discovery_uses_custom_base(monkeypatch):
    calls = []

    async def fake_request(method, url, **kwargs):
        calls.append((method, url))
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"data": [{"id": "example-model"}, {"id": "text-embedding-3-small"}]},
        )

    monkeypatch.setattr("services.models_service._http_request_with_retry", fake_request)
    service = ModelsService()

    result = await service.get_openai_models(
        "test-key", api_base="https://gateway.example/openai", update_index=False
    )

    assert calls == [("GET", "https://gateway.example/openai/models")]
    assert [model["value"] for model in result["language_models"]] == ["example-model"]
