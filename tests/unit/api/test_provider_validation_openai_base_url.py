"""Coverage for the OpenAI custom base-URL override reaching provider
validation (openrag issue #2060).

Before this fix, `_test_openai_lightweight_health`, `_test_openai_completion_with_tools`,
and `_test_openai_embedding` hardcoded `https://api.openai.com`, so
`validate_provider_setup()` - called from both `update_settings` (PATCH
/settings) and `onboarding` (POST /onboarding) - always validated a
gateway-only API key against the real OpenAI API and rejected it with a 400,
even when `openai_base_url` was configured correctly everywhere else.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import api.provider_validation as provider_validation
from api.provider_validation import (
    _openai_base_url,
    _test_openai_completion_with_tools,
    _test_openai_embedding,
    _test_openai_lightweight_health,
    validate_provider_setup,
)

# Imported under an alias: pytest would otherwise try to collect these
# `test_*`-named production functions as test cases themselves.
dispatch_lightweight_health = provider_validation.test_lightweight_health
dispatch_completion_with_tools = provider_validation.test_completion_with_tools
dispatch_embedding = provider_validation.test_embedding

CUSTOM_BASE_URL = "http://localhost:4444/v1"


def _resp(status_code: int, json_data: dict) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.text = str(json_data)
    r.json.return_value = json_data
    return r


@pytest.fixture
def mock_client(monkeypatch):
    c = AsyncMock(spec=httpx.AsyncClient)
    c.__aenter__.return_value = c
    monkeypatch.setattr(provider_validation.httpx, "AsyncClient", MagicMock(return_value=c))
    return c


class TestOpenaiBaseUrlHelper:
    def test_defaults_to_real_openai(self):
        assert _openai_base_url(None) == "https://api.openai.com/v1"

    def test_uses_configured_base_url(self):
        assert _openai_base_url(CUSTOM_BASE_URL) == CUSTOM_BASE_URL

    def test_strips_trailing_slash(self):
        assert _openai_base_url("http://localhost:4444/v1/") == CUSTOM_BASE_URL


class TestLightweightHealthRespectsBaseUrl:
    @pytest.mark.asyncio
    async def test_hits_configured_gateway(self, mock_client):
        mock_client.get.return_value = _resp(200, {"data": []})

        await _test_openai_lightweight_health("sk-test", CUSTOM_BASE_URL)

        called_url = mock_client.get.call_args.args[0]
        assert called_url == f"{CUSTOM_BASE_URL}/models"

    @pytest.mark.asyncio
    async def test_falls_back_to_real_openai_when_unset(self, mock_client):
        mock_client.get.return_value = _resp(200, {"data": []})

        await _test_openai_lightweight_health("sk-test", None)

        called_url = mock_client.get.call_args.args[0]
        assert called_url == "https://api.openai.com/v1/models"


class TestCompletionWithToolsRespectsBaseUrl:
    @pytest.mark.asyncio
    async def test_hits_configured_gateway(self, mock_client):
        mock_client.post.return_value = _resp(200, {"choices": []})

        await _test_openai_completion_with_tools("sk-test", "gpt-4o-mini", CUSTOM_BASE_URL)

        called_url = mock_client.post.call_args.args[0]
        assert called_url == f"{CUSTOM_BASE_URL}/chat/completions"


class TestEmbeddingRespectsBaseUrl:
    @pytest.mark.asyncio
    async def test_hits_configured_gateway(self, mock_client):
        mock_client.post.return_value = _resp(200, {"data": [{"embedding": [0.1]}]})

        await _test_openai_embedding("sk-test", "text-embedding-3-small", CUSTOM_BASE_URL)

        called_url = mock_client.post.call_args.args[0]
        assert called_url == f"{CUSTOM_BASE_URL}/embeddings"


class TestDispatchFunctionsThreadEndpointForOpenai:
    """Regression guard: the provider=='openai' branches in the three
    dispatch functions must forward `endpoint` to the `_test_openai_*`
    helpers, the same way the watsonx/ollama branches already do."""

    @pytest.mark.asyncio
    async def test_lightweight_health_dispatch_forwards_endpoint(self, mock_client):
        mock_client.get.return_value = _resp(200, {"data": []})

        await dispatch_lightweight_health(
            provider="openai", api_key="sk-test", endpoint=CUSTOM_BASE_URL
        )

        assert mock_client.get.call_args.args[0] == f"{CUSTOM_BASE_URL}/models"

    @pytest.mark.asyncio
    async def test_completion_with_tools_dispatch_forwards_endpoint(self, mock_client):
        mock_client.post.return_value = _resp(200, {"choices": []})

        await dispatch_completion_with_tools(
            provider="openai", api_key="sk-test", llm_model="gpt-4o-mini", endpoint=CUSTOM_BASE_URL
        )

        assert mock_client.post.call_args.args[0] == f"{CUSTOM_BASE_URL}/chat/completions"

    @pytest.mark.asyncio
    async def test_embedding_dispatch_forwards_endpoint(self, mock_client):
        mock_client.post.return_value = _resp(200, {"data": [{"embedding": [0.1]}]})

        await dispatch_embedding(
            provider="openai",
            api_key="sk-test",
            embedding_model="text-embedding-3-small",
            endpoint=CUSTOM_BASE_URL,
        )

        assert mock_client.post.call_args.args[0] == f"{CUSTOM_BASE_URL}/embeddings"


class TestValidateProviderSetupEndToEnd:
    """The full entry point used by endpoints.py: onboarding/settings must
    not validate a gateway-only key against the real OpenAI API."""

    @pytest.mark.asyncio
    async def test_lightweight_validation_uses_configured_gateway(self, mock_client):
        mock_client.get.return_value = _resp(200, {"data": []})

        await validate_provider_setup(provider="openai", api_key="sk-test", endpoint=CUSTOM_BASE_URL)

        assert mock_client.get.call_args.args[0] == f"{CUSTOM_BASE_URL}/models"

    @pytest.mark.asyncio
    async def test_full_validation_uses_configured_gateway_for_embedding(self, mock_client):
        mock_client.post.return_value = _resp(200, {"data": [{"embedding": [0.1]}]})

        await validate_provider_setup(
            provider="openai",
            api_key="sk-test",
            embedding_model="text-embedding-3-small",
            endpoint=CUSTOM_BASE_URL,
            test_completion=True,
        )

        assert mock_client.post.call_args.args[0] == f"{CUSTOM_BASE_URL}/embeddings"
