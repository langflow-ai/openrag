"""Unit tests for OpenAI provider check timeout & retry behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from api.provider_validation import (
    _http_request_with_retry,
    _test_azure_lightweight_health,
    _test_openai_lightweight_health,
    _test_watsonx_completion_with_tools,
    _test_watsonx_embedding,
    _test_watsonx_lightweight_health,
    validate_provider_setup,
)


@pytest.mark.asyncio
async def test_http_request_with_retry_recovers_from_transient_timeout():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    # Attempt 1 times out, Attempt 2 returns 200 OK
    ok_response = httpx.Response(200, json={"data": [{"id": "gpt-4o"}]})
    mock_client.get.side_effect = [
        httpx.TimeoutException("Read timed out"),
        ok_response,
    ]

    resp = await _http_request_with_retry(
        "GET",
        "https://api.openai.com/v1/models",
        max_retries=2,
        backoff_factor=0.01,
        client=mock_client,
    )

    assert resp.status_code == 200
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_http_request_with_retry_recovers_from_503_status():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    service_unavailable = httpx.Response(503, text="Service Unavailable")
    ok_response = httpx.Response(200, json={"data": []})
    mock_client.get.side_effect = [service_unavailable, ok_response]

    resp = await _http_request_with_retry(
        "GET",
        "https://api.openai.com/v1/models",
        max_retries=2,
        backoff_factor=0.01,
        client=mock_client,
    )

    assert resp.status_code == 200
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_http_request_with_retry_does_not_retry_auth_failure():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    unauthorized = httpx.Response(401, json={"error": {"message": "Invalid API key"}})
    mock_client.get.return_value = unauthorized

    resp = await _http_request_with_retry(
        "GET",
        "https://api.openai.com/v1/models",
        max_retries=2,
        backoff_factor=0.01,
        client=mock_client,
    )

    assert resp.status_code == 401
    assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_post_timeout_does_not_retry_without_flag():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.TimeoutException("POST timed out")

    with pytest.raises(httpx.TimeoutException):
        await _http_request_with_retry(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            max_retries=2,
            backoff_factor=0.01,
            retry_timeout_on_post=False,
            client=mock_client,
        )

    # Must NOT retry POST on ambiguous network timeout without explicit flag
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_post_timeout_retries_with_explicit_flag():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    ok_response = httpx.Response(200, json={"choices": []})
    mock_client.post.side_effect = [
        httpx.TimeoutException("POST timed out"),
        ok_response,
    ]

    resp = await _http_request_with_retry(
        "POST",
        "https://api.openai.com/v1/chat/completions",
        max_retries=2,
        backoff_factor=0.01,
        retry_timeout_on_post=True,
        client=mock_client,
    )

    assert resp.status_code == 200
    assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_openai_lightweight_health_succeeds_with_retry(monkeypatch):
    ok_response = httpx.Response(200, json={"data": [{"id": "gpt-4o"}]})
    attempts = 0

    async def fake_retry(method, url, **kwargs):
        nonlocal attempts
        attempts += 1
        return ok_response

    monkeypatch.setattr("api.provider_validation._http_request_with_retry", fake_retry)

    # Should run cleanly without raising exception
    await _test_openai_lightweight_health("sk-test-key")
    assert attempts == 1


@pytest.mark.asyncio
async def test_azure_lightweight_health_checks_endpoint_and_key(monkeypatch):
    captured = {}

    async def fake_retry(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr("api.provider_validation._http_request_with_retry", fake_retry)

    await _test_azure_lightweight_health(
        {
            "api_key": "azure-key",
            "api_base": "https://example.openai.azure.com/",
            "api_version": "2024-10-21",
        }
    )

    assert captured["method"] == "GET"
    assert captured["url"] == "https://example.openai.azure.com/openai/models"
    assert captured["headers"]["api-key"] == "azure-key"
    assert captured["params"] == {"api-version": "2024-10-21"}


@pytest.mark.asyncio
async def test_azure_foundry_lightweight_health_checks_endpoint_and_key(monkeypatch):
    captured = {}

    async def fake_retry(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return httpx.Response(200, json={"data": [{"id": "test-model"}]})

    monkeypatch.setattr("api.provider_validation._http_request_with_retry", fake_retry)

    await _test_azure_lightweight_health(
        {
            "api_key": "azure-key",
            "api_base": "https://example.services.ai.azure.com/",
        }
    )

    assert captured["method"] == "GET"
    assert captured["url"] == "https://example.services.ai.azure.com/openai/v1/models"
    assert captured["headers"]["api-key"] == "azure-key"
    assert captured["params"] is None


@pytest.mark.asyncio
async def test_azure_lightweight_health_rejects_missing_credentials():
    with pytest.raises(ValueError, match="Azure credentials are required"):
        await _test_azure_lightweight_health({"api_base": "https://example.openai.azure.com"})


@pytest.mark.asyncio
async def test_azure_lightweight_health_rejects_http_before_request(monkeypatch):
    retry = AsyncMock(side_effect=AssertionError("HTTP request must not be sent"))
    monkeypatch.setattr("api.provider_validation._http_request_with_retry", retry)

    with pytest.raises(ValueError, match="Azure endpoint must use HTTPS"):
        await _test_azure_lightweight_health(
            {"api_key": "azure-key", "api_base": "http://example.openai.azure.com"}
        )

    retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_azure_foundry_model_probe_rejects_http_before_litellm(monkeypatch):
    litellm_probe = AsyncMock(side_effect=AssertionError("LiteLLM request must not be sent"))
    monkeypatch.setattr("api.provider_validation._test_litellm_provider", litellm_probe)

    with pytest.raises(ValueError, match="Azure endpoint must use HTTPS"):
        await validate_provider_setup(
            provider="azure",
            llm_model="gpt-4.1",
            credentials={
                "api_key": "azure-key",
                "api_base": "http://example.services.ai.azure.com/",
            },
        )

    litellm_probe.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "probe,args",
    [
        (_test_watsonx_lightweight_health, ("ibm-key", "http://wx.example.com", "project")),
        (
            _test_watsonx_completion_with_tools,
            ("ibm-key", "model", "http://wx.example.com", "project"),
        ),
        (
            _test_watsonx_embedding,
            ("ibm-key", "embedding-model", "http://wx.example.com", "project"),
        ),
    ],
)
async def test_watsonx_probes_reject_http_before_request(monkeypatch, probe, args):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("HTTP client must not be created")

    monkeypatch.setattr("api.provider_validation.httpx.AsyncClient", unexpected_client)

    with pytest.raises(ValueError, match="watsonx endpoint must use HTTPS"):
        await probe(*args)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "probe,args,provider_url,provider_response",
    [
        (
            _test_watsonx_lightweight_health,
            ("ibm-key", "https://wx.example.com", "project"),
            None,
            None,
        ),
        (
            _test_watsonx_completion_with_tools,
            ("ibm-key", "model", "https://wx.example.com", "project"),
            "https://wx.example.com/ml/v1/text/chat",
            {"results": []},
        ),
        (
            _test_watsonx_embedding,
            ("ibm-key", "embedding-model", "https://wx.example.com", "project"),
            "https://wx.example.com/ml/v1/text/embeddings",
            {"results": [{"embedding": [0.1]}]},
        ),
    ],
)
async def test_watsonx_https_probes_keep_existing_requests(
    monkeypatch, probe, args, provider_url, provider_response
):
    from unittest.mock import Mock

    class Client:
        def __init__(self, response):
            self.post = AsyncMock(return_value=response)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    iam = Client(httpx.Response(200, json={"access_token": "bearer"}))
    provider_client = Client(httpx.Response(200, json=provider_response or {}))
    clients = [iam] if provider_url is None else [iam, provider_client]
    client_factory = Mock(side_effect=clients)
    monkeypatch.setattr("api.provider_validation.httpx.AsyncClient", client_factory)

    await probe(*args)

    assert iam.post.await_args.args[0] == "https://iam.cloud.ibm.com/identity/token"
    assert iam.post.await_args.kwargs["data"]["apikey"] == "ibm-key"
    if provider_url:
        assert provider_client.post.await_args.args[0] == provider_url
        assert provider_client.post.await_args.kwargs["headers"]["Authorization"] == "Bearer bearer"


@pytest.mark.asyncio
async def test_azure_foundry_endpoint_uses_the_litellm_route(monkeypatch):
    """Foundry resource roots must retain main's Azure/LiteLLM behavior."""
    litellm_probe = AsyncMock()
    health_check = AsyncMock()
    monkeypatch.setattr("api.provider_validation._test_litellm_provider", litellm_probe)
    monkeypatch.setattr("api.provider_validation.test_lightweight_health", health_check)

    await validate_provider_setup(
        provider="azure",
        llm_model="gpt-4.1",
        credentials={
            "api_key": "azure-key",
            "api_base": "https://example.services.ai.azure.com/",
        },
    )

    litellm_probe.assert_awaited_once()
    health_check.assert_not_awaited()
