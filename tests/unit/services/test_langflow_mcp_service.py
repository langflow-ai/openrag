import pytest

import services.langflow_mcp_service as mcp_module
from services.langflow_mcp_service import (
    LangflowMCPService,
    MCPServerURLUpdateError,
)


class _Response:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            req = httpx.Request("PATCH", "http://test")
            resp = httpx.Response(self.status_code, text=self.text, request=req)
            raise httpx.HTTPStatusError(
                f"Status {self.status_code}", request=req, response=resp
            )


@pytest.mark.asyncio
async def test_update_all_mcp_server_urls_strict_raises_with_failed_server(
    monkeypatch,
):
    service = LangflowMCPService()

    async def fake_list_mcp_servers():
        return [{"name": "lf-starter_project"}]

    async def fake_patch_mcp_server_url(server_name: str):
        assert server_name == "lf-starter_project"
        return "failed"

    monkeypatch.setattr(service, "list_mcp_servers", fake_list_mcp_servers)
    monkeypatch.setattr(service, "patch_mcp_server_url", fake_patch_mcp_server_url)

    with pytest.raises(MCPServerURLUpdateError) as exc_info:
        await service.update_all_mcp_server_urls(strict=True)

    assert exc_info.value.summary["failed"] == 1
    assert exc_info.value.summary["failed_servers"] == ["lf-starter_project"]
    assert "lf-starter_project" in str(exc_info.value)


@pytest.mark.asyncio
async def test_patch_mcp_server_url_retries_retryable_patch_status(monkeypatch):
    service = LangflowMCPService()
    monkeypatch.setenv("LANGFLOW_URL", "http://langflow:7860")

    async def fake_get_mcp_server(server_name: str):
        assert server_name == "lf-starter_project"
        return {"url": "http://localhost:8000/mcp"}

    patch_requests = []

    async def fake_langflow_request(**kwargs):
        patch_requests.append(kwargs)
        if len(patch_requests) < 3:
            return _Response(503, "Langflow warming up")
        return _Response(200, "ok")

    monkeypatch.setattr(service, "get_mcp_server", fake_get_mcp_server)
    monkeypatch.setattr(
        mcp_module.clients,
        "langflow_request",
        fake_langflow_request,
        raising=True,
    )

    result = await service.patch_mcp_server_url("lf-starter_project")

    assert result == "patched"
    assert len(patch_requests) == 3
    assert patch_requests[-1]["json"]["url"] == "http://langflow:7860/mcp"
    assert patch_requests[-1]["json"]["headers"] == mcp_module.REQUIRED_MCP_HEADERS


@pytest.mark.asyncio
async def test_patch_mcp_server_url_preserves_auth_settings(monkeypatch):
    service = LangflowMCPService()
    monkeypatch.setenv("LANGFLOW_URL", "http://langflow:7860")

    async def fake_get_mcp_server(server_name: str):
        assert server_name == "lf-starter_project"
        return {
            "url": "http://localhost:7860/api/v1/mcp/project/project-id/streamable",
            "auth_type": "api_key",
            "headers": {
                "x-api-key": "langflow-key",
                "X-Langflow-Global-Var-JWT": "JWT",
            },
        }

    patch_requests = []

    async def fake_langflow_request(**kwargs):
        patch_requests.append(kwargs)
        return _Response(200, "ok")

    monkeypatch.setattr(service, "get_mcp_server", fake_get_mcp_server)
    monkeypatch.setattr(
        mcp_module.clients,
        "langflow_request",
        fake_langflow_request,
        raising=True,
    )

    result = await service.patch_mcp_server_url("lf-starter_project")

    assert result == "patched"
    expected_headers = {
        "x-api-key": "langflow-key",
        "X-Langflow-Global-Var-JWT": "JWT",
        **mcp_module.REQUIRED_MCP_HEADERS,
    }
    assert patch_requests == [
        {
            "method": "PATCH",
            "endpoint": "/api/v2/mcp/servers/lf-starter_project",
            "json": {
                "url": "http://langflow:7860/api/v1/mcp/project/project-id/streamable",
                "headers": expected_headers,
            },
        }
    ]
