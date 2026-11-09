"""`GET /docling/health`: a busy docling-serve is degraded, not stopped."""

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from api import docling


def _patch_client(monkeypatch, *, raises=None, status_code=200):
    client = MagicMock()
    if raises is not None:
        client.get = AsyncMock(side_effect=raises)
    else:
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(docling.httpx, "AsyncClient", MagicMock(return_value=client))
    return client


async def _call():
    response = await docling.health(MagicMock(), user=None)
    return response.status_code, json.loads(response.body)


@pytest.mark.asyncio
async def test_healthy(monkeypatch):
    client = _patch_client(monkeypatch, status_code=200)

    status_code, body = await _call()

    assert status_code == 200
    assert body["status"] == "healthy"
    assert client.get.call_args.kwargs["timeout"] == docling._HEALTH_CHECK_TIMEOUT_S


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc", [httpx.ReadTimeout(""), httpx.WriteTimeout(""), httpx.PoolTimeout("")]
)
async def test_slow_reply_is_degraded_not_unhealthy(monkeypatch, exc):
    _patch_client(monkeypatch, raises=exc)

    status_code, body = await _call()

    assert status_code == 200
    assert body["status"] == "degraded"
    assert "slow to respond" in body["message"]


@pytest.mark.asyncio
async def test_connect_timeout_is_unhealthy(monkeypatch):
    _patch_client(monkeypatch, raises=httpx.ConnectTimeout(""))

    status_code, body = await _call()

    assert status_code == 503
    assert body["status"] == "unhealthy"
    assert body["message"] == "Connection timeout"


@pytest.mark.asyncio
async def test_connection_refused_is_unhealthy(monkeypatch):
    _patch_client(monkeypatch, raises=httpx.ConnectError("refused"))

    status_code, body = await _call()

    assert status_code == 503
    assert body["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_non_200_is_unhealthy(monkeypatch):
    _patch_client(monkeypatch, status_code=500)

    status_code, body = await _call()

    assert status_code == 503
    assert body["status"] == "unhealthy"
