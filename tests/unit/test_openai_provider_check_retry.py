"""Unit tests for OpenAI provider check timeout & retry behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from api.provider_validation import _http_request_with_retry, _test_openai_lightweight_health


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
