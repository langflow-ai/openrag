"""Unit tests for DoclingService.check_task_status and fetch_task_result.

These are the single-poll primitives that the backend's polling coordinator
uses instead of the legacy in-method polling loop.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
import httpx
from services.docling_service import (
    DoclingService,
    DoclingServeError,
    DoclingTaskState,
)


def _resp(status_code: int, json_data: dict | None = None, text: str = "") -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.text = text
    if json_data is not None:
        r.json.return_value = json_data
    else:
        r.json.side_effect = ValueError("no json")
    return r


@pytest.fixture
def mock_client():
    c = AsyncMock(spec=httpx.AsyncClient)
    c.__aenter__.return_value = c
    return c


@pytest.fixture
def docling_service(mock_client):
    return DoclingService(docling_url="http://docling:8000", httpx_client=mock_client)


# ── check_task_status ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_status_success(docling_service, mock_client):
    mock_client.get.return_value = _resp(200, {"task_status": "success"})

    snap = await docling_service.check_task_status("t1")

    assert snap.state == DoclingTaskState.SUCCESS


@pytest.mark.asyncio
async def test_check_status_failure(docling_service, mock_client):
    mock_client.get.return_value = _resp(200, {"task_status": "failure", "error": "boom"})

    snap = await docling_service.check_task_status("t1")

    assert snap.state == DoclingTaskState.FAILED
    assert "boom" in (snap.detail or "")


@pytest.mark.asyncio
async def test_check_status_processing(docling_service, mock_client):
    mock_client.get.return_value = _resp(200, {"task_status": "started"})

    snap = await docling_service.check_task_status("t1")

    assert snap.state == DoclingTaskState.PROCESSING


@pytest.mark.asyncio
async def test_check_status_unknown_state_treated_as_pending(docling_service, mock_client):
    mock_client.get.return_value = _resp(200, {"task_status": "queued"})

    snap = await docling_service.check_task_status("t1")

    assert snap.state == DoclingTaskState.PENDING


@pytest.mark.asyncio
async def test_check_status_404_returns_not_found(docling_service, mock_client):
    mock_client.get.return_value = _resp(404, text="not found")

    snap = await docling_service.check_task_status("t1")

    assert snap.state == DoclingTaskState.NOT_FOUND


@pytest.mark.asyncio
async def test_check_status_5xx_treated_as_processing(docling_service, mock_client):
    """5xx is transient — surface as PROCESSING so the polling loop retries."""
    mock_client.get.return_value = _resp(503, text="bad gateway")

    snap = await docling_service.check_task_status("t1")

    assert snap.state == DoclingTaskState.PROCESSING


@pytest.mark.asyncio
async def test_check_status_4xx_other_treated_as_failed(docling_service, mock_client):
    mock_client.get.return_value = _resp(400, text="bad request")

    snap = await docling_service.check_task_status("t1")

    assert snap.state == DoclingTaskState.FAILED


@pytest.mark.asyncio
async def test_check_status_network_error_treated_as_processing(docling_service, mock_client):
    mock_client.get.side_effect = httpx.ConnectError("connection refused")

    snap = await docling_service.check_task_status("t1")

    assert snap.state == DoclingTaskState.PROCESSING


# ── fetch_task_result ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_result_success(docling_service, mock_client):
    mock_client.get.return_value = _resp(200, {"document": {"json_content": {"k": "v"}}})

    out = await docling_service.fetch_task_result("t1")

    assert out == {"k": "v"}


@pytest.mark.asyncio
async def test_fetch_result_404_raises(docling_service, mock_client):
    mock_client.get.return_value = _resp(404, text="not found")

    with pytest.raises(DoclingServeError, match="not found"):
        await docling_service.fetch_task_result("t1")


@pytest.mark.asyncio
async def test_fetch_result_5xx_raises(docling_service, mock_client):
    mock_client.get.return_value = _resp(500, text="internal")

    with pytest.raises(DoclingServeError, match="HTTP 500"):
        await docling_service.fetch_task_result("t1")


@pytest.mark.asyncio
async def test_fetch_result_missing_json_content_raises(docling_service, mock_client):
    mock_client.get.return_value = _resp(200, {"document": {}})

    with pytest.raises(DoclingServeError, match="missing document.json_content"):
        await docling_service.fetch_task_result("t1")


@pytest.mark.asyncio
async def test_fetch_result_network_error_raises(docling_service, mock_client):
    mock_client.get.side_effect = httpx.ConnectError("dns error")

    with pytest.raises(DoclingServeError, match="Network error"):
        await docling_service.fetch_task_result("t1")
