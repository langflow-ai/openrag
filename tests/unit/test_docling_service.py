"""
Unit tests for services/docling_service.py
Validates async conversion logic, polling behavior, and error handling.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from services.docling_service import DoclingService, DoclingServeError

def _make_response(status_code: int, json_data: dict = None) -> MagicMock:
    """Create a mock HTTP response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    
    # Mock raise_for_status to raise if status_code >= 400
    if status_code >= 400:
        def raise_status():
            raise httpx.HTTPStatusError("Error", request=MagicMock(), response=resp)
        resp.raise_for_status.side_effect = raise_status
    else:
        resp.raise_for_status.return_value = None
        
    return resp

@pytest.fixture
def mock_httpx_client():
    """Provide a mocked httpx AsyncClient."""
    client = AsyncMock(spec=httpx.AsyncClient)
    # Mock __aenter__ and __aexit__ for 'async with client' support
    client.__aenter__.return_value = client
    return client

@pytest.fixture
def docling_service(mock_httpx_client):
    """Provide a DoclingService instance with a mocked client."""
    return DoclingService(docling_url="http://docling:8000", httpx_client=mock_httpx_client)

@pytest.fixture(autouse=True)
def no_sleep():
    """Patch asyncio.sleep so tests run instantly."""
    with patch("services.docling_service.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        yield mock_sleep

# ── Polling Logic ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poll_result_success(docling_service, mock_httpx_client):
    """Returns json_content when Docling returns 'success'."""
    # First call: status poll -> success
    # Second call: get result -> document data
    mock_httpx_client.get.side_effect = [
        _make_response(200, {"task_status": "success"}),
        _make_response(200, {"document": {"json_content": {"key": "value"}}})
    ]
    
    result = await docling_service._poll_result(mock_httpx_client, "task123", 1.0, 10.0)
    assert result == {"key": "value"}
    assert mock_httpx_client.get.call_count == 2
    # Verify URLs
    calls = mock_httpx_client.get.call_args_list
    assert calls[0].args[0].endswith("/v1/status/poll/task123")
    assert calls[1].args[0].endswith("/v1/result/task123")

@pytest.mark.asyncio
async def test_poll_result_waits_for_pending(docling_service, mock_httpx_client, no_sleep):
    """Polls multiple times if status is 'pending' before succeeding."""
    mock_httpx_client.get.side_effect = [
        _make_response(200, {"task_status": "pending"}),
        _make_response(200, {"task_status": "pending"}),
        _make_response(200, {"task_status": "success"}),
        _make_response(200, {"document": {"json_content": {"key": "value"}}})
    ]
    
    result = await docling_service._poll_result(mock_httpx_client, "task123", 1.0, 10.0)
    assert result == {"key": "value"}
    assert mock_httpx_client.get.call_count == 4
    assert no_sleep.call_count == 2

@pytest.mark.asyncio
async def test_poll_result_failure_status(docling_service, mock_httpx_client):
    """Raises DoclingServeError when status is 'failure'."""
    mock_httpx_client.get.return_value = _make_response(200, {"task_status": "failure"})
    
    with pytest.raises(DoclingServeError, match="Docling conversion failed"):
        await docling_service._poll_result(mock_httpx_client, "task123", 1.0, 10.0)

@pytest.mark.asyncio
async def test_poll_result_timeout(docling_service, mock_httpx_client, no_sleep):
    """Raises TimeoutError when task stays pending beyond timeout."""
    mock_httpx_client.get.return_value = _make_response(200, {"task_status": "pending"})
    
    # timeout=2.0, interval=1.0 -> loop runs at T=0, T=1, exits at T=2
    with pytest.raises(TimeoutError, match="did not complete within"):
        await docling_service._poll_result(mock_httpx_client, "task123", 1.0, 2.0)
    
    assert mock_httpx_client.get.call_count == 2
    assert no_sleep.call_count == 2

@pytest.mark.asyncio
async def test_poll_result_missing_content(docling_service, mock_httpx_client):
    """Raises DoclingServeError if result response is missing json_content."""
    mock_httpx_client.get.side_effect = [
        _make_response(200, {"task_status": "success"}),
        _make_response(200, {"document": {}}) # No json_content
    ]
    
    with pytest.raises(DoclingServeError, match="missing document.json_content"):
        await docling_service._poll_result(mock_httpx_client, "task123", 1.0, 10.0)

@pytest.mark.asyncio
async def test_poll_result_http_error(docling_service, mock_httpx_client):
    """Propagates HTTP errors during polling as DoclingServeError."""
    mock_httpx_client.get.return_value = _make_response(500)
    
    with pytest.raises(DoclingServeError, match="Error polling docling status"):
        await docling_service._poll_result(mock_httpx_client, "task123", 1.0, 10.0)

# ── Upload Logic ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_success(docling_service, mock_httpx_client):
    """Returns task_id on successful upload."""
    mock_httpx_client.post.return_value = _make_response(200, {"task_id": "new-task-id"})
    
    # Mock config to avoid missing attribute errors during _build_docling_options
    with patch("services.docling_service.get_openrag_config") as mock_get_config:
        mock_config = MagicMock()
        mock_config.knowledge.table_structure = False
        mock_config.knowledge.ocr = False
        mock_config.knowledge.picture_descriptions = False
        mock_get_config.return_value = mock_config
        
        task_id = await docling_service.upload_to_docling_direct_async("test.pdf", b"data")
        
    assert task_id == "new-task-id"
    assert mock_httpx_client.post.call_count == 1
    
    # Verify boolean serialization (bool -> "true"/"false")
    _, kwargs = mock_httpx_client.post.call_args
    data = kwargs.get("data", {})
    assert data["do_ocr"] == "false"

@pytest.mark.asyncio
async def test_upload_http_error(docling_service, mock_httpx_client):
    """Raises exception if upload returns non-200."""
    mock_httpx_client.post.return_value = _make_response(400)
    
    with patch("services.docling_service.get_openrag_config"):
        with pytest.raises(httpx.HTTPStatusError):
            await docling_service.upload_to_docling_direct_async("test.pdf", b"data")

# ── Configuration Logic ─────────────────────────────────────────────

def test_build_docling_options_toggles(docling_service):
    """Correctly maps OpenRAG config to Docling options."""
    mock_config = MagicMock()
    mock_config.knowledge.table_structure = True
    mock_config.knowledge.ocr = True
    mock_config.knowledge.picture_descriptions = False
    
    with patch("services.docling_service.get_openrag_config", return_value=mock_config):
        options = docling_service._build_docling_options()
        
    assert options["do_table_structure"] is True
    assert options["do_ocr"] is True
    assert options["do_picture_description"] is False
    assert options["to_formats"] == "json"

def test_preset_configs_macos():
    """Uses ocrmac engine on macOS."""
    from services.docling_service import get_docling_preset_configs
    with patch("services.docling_service.platform.system", return_value="Darwin"):
        preset = get_docling_preset_configs(ocr=True)
        assert preset["ocr_engine"] == "ocrmac"

def test_preset_configs_linux():
    """Uses easyocr engine on non-macOS."""
    from services.docling_service import get_docling_preset_configs
    with patch("services.docling_service.platform.system", return_value="Linux"):
        preset = get_docling_preset_configs(ocr=True)
        assert preset["ocr_engine"] == "easyocr"

def test_init_default_url():
    """Uses DOCLING_SERVICE_URL from api.docling if not provided."""
    with patch("api.docling.DOCLING_SERVICE_URL", "http://default:5001"):
        service = DoclingService()
        assert service.docling_url == "http://default:5001"
