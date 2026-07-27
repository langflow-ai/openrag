"""Unit tests for the FileNet P8 MCP startup registration wiring.

``startup_orchestrator._ensure_filenet_mcp_server`` must:
- no-op unless ``is_filenet_mcp_available()`` (kill switch AND on_prem-or-dev
  gate AND configured URL);
- register the ``filenet-p8`` server create-only, with the bearer header only
  when a token is configured;
- run the startup diagnostics afterwards;
- swallow (log-and-continue) every failure — startup must never break.
"""

from unittest.mock import AsyncMock

import pytest

import services.filenet_mcp_diagnostics as diag_module
import services.startup_orchestrator as orchestrator
from services.startup_orchestrator import _ensure_filenet_mcp_server

MCP_URL = "http://filenet-mcp:8811/mcp"


class _FakeMCPService:
    def __init__(self, result="created", error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def ensure_mcp_server(self, server_name, server_config):
        self.calls.append((server_name, server_config))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def diagnostics_spy(monkeypatch):
    spy = AsyncMock(return_value=None)
    monkeypatch.setattr(diag_module, "run_filenet_startup_diagnostics", spy)
    return spy


def _enable_filenet(monkeypatch, token=""):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "on_prem")
    monkeypatch.setenv("OPENRAG_FILENET_MCP_ENABLED", "true")
    monkeypatch.delenv("OPENRAG_DEV_FILENET_MCP", raising=False)
    monkeypatch.setenv("OPENRAG_FILENET_MCP_URL", MCP_URL)
    if token:
        monkeypatch.setenv("OPENRAG_FILENET_MCP_TOKEN", token)
    else:
        monkeypatch.delenv("OPENRAG_FILENET_MCP_TOKEN", raising=False)


@pytest.mark.asyncio
async def test_skipped_when_unavailable(monkeypatch, diagnostics_spy):
    """OSS run mode without the dev bypass: nothing is registered or probed."""
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.delenv("OPENRAG_DEV_FILENET_MCP", raising=False)
    monkeypatch.setenv("OPENRAG_FILENET_MCP_URL", MCP_URL)
    service = _FakeMCPService()

    await _ensure_filenet_mcp_server(service)

    assert service.calls == []
    diagnostics_spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_skipped_when_kill_switch_off(monkeypatch, diagnostics_spy):
    _enable_filenet(monkeypatch)
    monkeypatch.setenv("OPENRAG_FILENET_MCP_ENABLED", "false")
    service = _FakeMCPService()

    await _ensure_filenet_mcp_server(service)

    assert service.calls == []
    diagnostics_spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_registers_without_headers_when_no_token(monkeypatch, diagnostics_spy):
    _enable_filenet(monkeypatch)
    service = _FakeMCPService()

    await _ensure_filenet_mcp_server(service)

    assert service.calls == [("filenet-p8", {"url": MCP_URL})]
    diagnostics_spy.assert_awaited_once()


@pytest.mark.asyncio
async def test_registers_with_bearer_header_when_token_set(monkeypatch, diagnostics_spy):
    _enable_filenet(monkeypatch, token="shared-secret")
    service = _FakeMCPService()

    await _ensure_filenet_mcp_server(service)

    assert service.calls == [
        (
            "filenet-p8",
            {"url": MCP_URL, "headers": {"Authorization": "Bearer shared-secret"}},
        )
    ]


@pytest.mark.asyncio
async def test_dev_bypass_enables_in_oss(monkeypatch, diagnostics_spy):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setenv("OPENRAG_DEV_FILENET_MCP", "true")
    monkeypatch.setenv("OPENRAG_FILENET_MCP_ENABLED", "true")
    monkeypatch.setenv("OPENRAG_FILENET_MCP_URL", MCP_URL)
    monkeypatch.delenv("OPENRAG_FILENET_MCP_TOKEN", raising=False)
    service = _FakeMCPService()

    await _ensure_filenet_mcp_server(service)

    assert len(service.calls) == 1


@pytest.mark.asyncio
async def test_registration_failure_does_not_raise_and_diagnostics_still_run(
    monkeypatch, diagnostics_spy
):
    _enable_filenet(monkeypatch)
    service = _FakeMCPService(error=ConnectionError("langflow down"))

    await _ensure_filenet_mcp_server(service)  # must not raise

    assert len(service.calls) == 1
    diagnostics_spy.assert_awaited_once()


@pytest.mark.asyncio
async def test_diagnostics_failure_does_not_raise(monkeypatch, diagnostics_spy):
    _enable_filenet(monkeypatch)
    diagnostics_spy.side_effect = RuntimeError("diagnostics exploded")
    service = _FakeMCPService()

    await _ensure_filenet_mcp_server(service)  # must not raise

    assert len(service.calls) == 1


def test_startup_tasks_wiring_calls_helper_before_url_patching():
    """The orchestrator invokes the FileNet helper before _update_mcp_server_urls,
    so a newly registered filenet-p8 server is URL-normalized in the same pass."""
    import inspect

    source = inspect.getsource(orchestrator.startup_tasks)
    assert "_ensure_filenet_mcp_server" in source
    assert source.index("_ensure_filenet_mcp_server") < source.index("_update_mcp_server_urls")
