"""Langflow talks to the OpenRAG LLM proxy with the caller JWT, not provider keys."""

from types import SimpleNamespace

import pytest

from utils.langflow_headers import (
    add_provider_credentials_to_headers,
    build_model_provider_headers,
    proxy_bearer_token,
)


def test_proxy_bearer_token_strips_bearer_and_drops_basic():
    assert proxy_bearer_token("Bearer abc.def") == "abc.def"
    assert proxy_bearer_token("abc.def") == "abc.def"
    assert proxy_bearer_token("Basic dXNlcjpwYXNz") == ""
    assert proxy_bearer_token("") == ""
    assert proxy_bearer_token(None) == ""


def test_build_model_provider_headers_forces_openai_client():
    config = SimpleNamespace(
        knowledge=SimpleNamespace(embedding_model="text-embedding-3-small", embedding_provider="watsonx"),
        agent=SimpleNamespace(llm_model="claude-sonnet-4-5", llm_provider="anthropic"),
    )
    headers = build_model_provider_headers(config)
    assert headers["X-LANGFLOW-GLOBAL-VAR-SELECTED_LANGUAGE_MODEL"] == "claude-sonnet-4-5"
    assert headers["X-LANGFLOW-GLOBAL-VAR-SELECTED_LANGUAGE_MODEL_PROVIDER"] == "OpenAI"
    assert headers["X-LANGFLOW-GLOBAL-VAR-SELECTED_EMBEDDING_MODEL"] == "text-embedding-3-small"
    assert headers["X-LANGFLOW-GLOBAL-VAR-SELECTED_EMBEDDING_MODEL_PROVIDER"] == "OpenAI"


@pytest.mark.asyncio
async def test_add_provider_credentials_injects_jwt_not_provider_keys(monkeypatch):
    monkeypatch.setattr(
        "config.settings.get_langflow_llm_base_url",
        lambda: "http://openrag-backend:8000/v1",
    )
    monkeypatch.setattr("config.settings.get_langflow_opensearch_url", lambda: "")
    monkeypatch.setattr("config.settings.get_langflow_docling_url", lambda: "")
    monkeypatch.setattr("config.settings.get_index_name", lambda: "")
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", False)

    config = SimpleNamespace(
        providers=SimpleNamespace(
            openai=SimpleNamespace(api_key="sk-real-openai"),
            anthropic=SimpleNamespace(api_key="sk-ant-real"),
            watsonx=SimpleNamespace(api_key="wx-real", project_id="p", endpoint="https://wx"),
            ollama=SimpleNamespace(endpoint="http://localhost:11434"),
        )
    )
    headers = {}
    await add_provider_credentials_to_headers(
        headers, config, jwt_token="Bearer user-jwt-token"
    )
    assert headers["X-LANGFLOW-GLOBAL-VAR-OPENAI_API_KEY"] == "user-jwt-token"
    assert headers["X-LANGFLOW-GLOBAL-VAR-OPENRAG_LLM_BASE_URL"] == "http://openrag-backend:8000/v1"
    assert "sk-real-openai" not in headers.values()
    assert "sk-ant-real" not in headers.values()
    assert "wx-real" not in headers.values()
    assert "X-LANGFLOW-GLOBAL-VAR-ANTHROPIC_API_KEY" not in headers
    assert "X-LANGFLOW-GLOBAL-VAR-WATSONX_APIKEY" not in headers
