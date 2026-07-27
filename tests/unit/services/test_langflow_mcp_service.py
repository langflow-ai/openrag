"""Unit tests for LangflowMCPService.

Covers the URL-patching paths that exist in src today plus the
``ensure_mcp_server`` create-if-absent registration used for the FileNet P8
MCP server ("filenet-p8").

NOTE: this file previously asserted a stricter API (``MCPServerURLUpdateError``,
``strict=``, ``raise_on_error=``, ``patch_retry_*``) that never landed in src,
which made the module fail collection. It now tests the actual service API.
"""

import pytest

import services.langflow_mcp_service as mcp_module
from services.langflow_mcp_service import LangflowMCPService


class _Response:
    def __init__(self, status_code: int, text: str = "", json_data=None) -> None:
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


# ---------------------------------------------------------------------------
# patch_mcp_server_url / update_all_mcp_server_urls (existing API)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_mcp_server_url_rewrites_localhost(monkeypatch):
    service = LangflowMCPService()
    monkeypatch.setenv("LANGFLOW_URL", "http://langflow:7860")

    async def fake_get_mcp_server(server_name: str):
        assert server_name == "lf-starter_project"
        return {"url": "http://localhost:7860/api/v1/mcp/project/p1/streamable"}

    patch_requests = []

    async def fake_langflow_request(**kwargs):
        patch_requests.append(kwargs)
        return _Response(200, "ok")

    monkeypatch.setattr(service, "get_mcp_server", fake_get_mcp_server)
    monkeypatch.setattr(mcp_module.clients, "langflow_request", fake_langflow_request, raising=True)

    result = await service.patch_mcp_server_url("lf-starter_project")

    assert result == "patched"
    assert patch_requests == [
        {
            "method": "PATCH",
            "endpoint": "/api/v2/mcp/servers/lf-starter_project",
            "json": {"url": "http://langflow:7860/api/v1/mcp/project/p1/streamable"},
        }
    ]


@pytest.mark.asyncio
async def test_patch_mcp_server_url_skips_non_localhost_url(monkeypatch):
    """A FileNet sidecar URL (non-localhost) must be left completely alone."""
    service = LangflowMCPService()
    monkeypatch.setenv("LANGFLOW_URL", "http://langflow:7860")

    async def fake_get_mcp_server(server_name: str):
        return {"url": "http://filenet-mcp:8811/mcp", "headers": {"Authorization": "Bearer x"}}

    calls = []

    async def fake_langflow_request(**kwargs):  # pragma: no cover - must not be hit
        calls.append(kwargs)
        return _Response(200, "ok")

    monkeypatch.setattr(service, "get_mcp_server", fake_get_mcp_server)
    monkeypatch.setattr(mcp_module.clients, "langflow_request", fake_langflow_request, raising=True)

    result = await service.patch_mcp_server_url("filenet-p8")

    assert result == "skipped"
    assert calls == []


@pytest.mark.asyncio
async def test_patch_mcp_server_url_failure_is_reported_not_raised(monkeypatch):
    service = LangflowMCPService()
    monkeypatch.setenv("LANGFLOW_URL", "http://langflow:7860")

    async def fake_get_mcp_server(server_name: str):
        return {"url": "http://localhost:7860/mcp"}

    async def fake_langflow_request(**kwargs):
        return _Response(500, "boom")

    monkeypatch.setattr(service, "get_mcp_server", fake_get_mcp_server)
    monkeypatch.setattr(mcp_module.clients, "langflow_request", fake_langflow_request, raising=True)

    assert await service.patch_mcp_server_url("lf-starter_project") == "failed"


@pytest.mark.asyncio
async def test_update_all_mcp_server_urls_summary(monkeypatch):
    service = LangflowMCPService()

    async def fake_list_mcp_servers():
        return [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"no_name_key": True}]

    outcomes = {"a": "patched", "b": "skipped", "c": "failed"}

    async def fake_patch(server_name: str):
        return outcomes[server_name]

    monkeypatch.setattr(service, "list_mcp_servers", fake_list_mcp_servers)
    monkeypatch.setattr(service, "patch_mcp_server_url", fake_patch)

    summary = await service.update_all_mcp_server_urls()

    assert summary == {"patched": 1, "skipped": 1, "failed": 1, "total": 4}


@pytest.mark.asyncio
async def test_update_all_mcp_server_urls_empty_list(monkeypatch):
    service = LangflowMCPService()

    async def fake_list_mcp_servers():
        return []

    monkeypatch.setattr(service, "list_mcp_servers", fake_list_mcp_servers)
    summary = await service.update_all_mcp_server_urls()
    assert summary == {"patched": 0, "skipped": 0, "failed": 0, "total": 0}


# ---------------------------------------------------------------------------
# ensure_mcp_server (new: FileNet P8 registration path)
# ---------------------------------------------------------------------------

FILENET_CONFIG = {
    "url": "http://filenet-mcp:8811/mcp",
    "headers": {"Authorization": "Bearer shared-secret"},
}


def _request_recorder(script):
    """Return (recorder_fn, calls) where script maps (method, endpoint) -> response."""
    calls = []

    async def fake_langflow_request(**kwargs):
        calls.append(kwargs)
        key = (kwargs["method"], kwargs["endpoint"])
        result = script[key]
        if isinstance(result, Exception):
            raise result
        return result

    return fake_langflow_request, calls


@pytest.mark.asyncio
async def test_ensure_mcp_server_creates_when_absent(monkeypatch):
    service = LangflowMCPService()
    fake, calls = _request_recorder(
        {
            ("GET", "/api/v2/mcp/servers/filenet-p8"): _Response(404, "not found"),
            ("POST", "/api/v2/mcp/servers/filenet-p8"): _Response(201, "created"),
        }
    )
    monkeypatch.setattr(mcp_module.clients, "langflow_request", fake, raising=True)

    result = await service.ensure_mcp_server("filenet-p8", FILENET_CONFIG)

    assert result == "created"
    assert calls[1]["method"] == "POST"
    assert calls[1]["json"] == FILENET_CONFIG


@pytest.mark.asyncio
async def test_ensure_mcp_server_existing_left_untouched(monkeypatch):
    """Idempotency: an existing server (any config) is never overwritten."""
    service = LangflowMCPService()
    fake, calls = _request_recorder(
        {
            ("GET", "/api/v2/mcp/servers/filenet-p8"): _Response(
                200, json_data={"url": "http://user-edited:9999/mcp"}
            ),
        }
    )
    monkeypatch.setattr(mcp_module.clients, "langflow_request", fake, raising=True)

    result = await service.ensure_mcp_server("filenet-p8", FILENET_CONFIG)

    assert result == "exists"
    assert len(calls) == 1  # no POST issued


@pytest.mark.asyncio
async def test_ensure_mcp_server_falls_back_to_collection_endpoint(monkeypatch):
    """Some Langflow versions only accept POST on the collection endpoint."""
    service = LangflowMCPService()
    fake, calls = _request_recorder(
        {
            ("GET", "/api/v2/mcp/servers/filenet-p8"): _Response(404),
            ("POST", "/api/v2/mcp/servers/filenet-p8"): _Response(405, "method not allowed"),
            ("POST", "/api/v2/mcp/servers"): _Response(200, "created"),
        }
    )
    monkeypatch.setattr(mcp_module.clients, "langflow_request", fake, raising=True)

    result = await service.ensure_mcp_server("filenet-p8", FILENET_CONFIG)

    assert result == "created"
    assert calls[-1]["endpoint"] == "/api/v2/mcp/servers"
    assert calls[-1]["json"] == {"name": "filenet-p8", **FILENET_CONFIG}


@pytest.mark.asyncio
async def test_ensure_mcp_server_create_failure(monkeypatch):
    service = LangflowMCPService()
    fake, _ = _request_recorder(
        {
            ("GET", "/api/v2/mcp/servers/filenet-p8"): _Response(404),
            ("POST", "/api/v2/mcp/servers/filenet-p8"): _Response(400, "bad config"),
        }
    )
    monkeypatch.setattr(mcp_module.clients, "langflow_request", fake, raising=True)

    assert await service.ensure_mcp_server("filenet-p8", FILENET_CONFIG) == "failed"


@pytest.mark.asyncio
async def test_ensure_mcp_server_unexpected_get_status_skips_creation(monkeypatch):
    """A 500 on the existence check must NOT lead to a blind create."""
    service = LangflowMCPService()
    fake, calls = _request_recorder(
        {
            ("GET", "/api/v2/mcp/servers/filenet-p8"): _Response(500, "boom"),
        }
    )
    monkeypatch.setattr(mcp_module.clients, "langflow_request", fake, raising=True)

    result = await service.ensure_mcp_server("filenet-p8", FILENET_CONFIG)

    assert result == "failed"
    assert len(calls) == 1  # no POST issued


@pytest.mark.asyncio
async def test_ensure_mcp_server_exception_returns_failed(monkeypatch):
    service = LangflowMCPService()

    async def fake_langflow_request(**kwargs):
        raise ConnectionError("langflow down")

    monkeypatch.setattr(mcp_module.clients, "langflow_request", fake_langflow_request, raising=True)

    assert await service.ensure_mcp_server("filenet-p8", FILENET_CONFIG) == "failed"
