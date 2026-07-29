"""Unit tests for the FileNet P8 MCP backend startup diagnostics (r1.6).

The diagnostics probe the sidecar's /health and /diagnostics routes, log an
INFO/WARNING matrix, and must NEVER raise or block startup.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import services.filenet_mcp_diagnostics as diag_module
from services.filenet_mcp_diagnostics import (
    derive_admin_url,
    run_filenet_startup_diagnostics,
)

MCP_URL = "http://filenet-mcp:8811/mcp"

HEALTHY_PAYLOAD = {
    "cpe_reachable": True,
    "txe_annotation_class_present": True,
    "cbr_enabled": True,
    "object_store": "FNOS1DS",
    "document_class": "Document",
    "errors": [],
}


@pytest.fixture
def fake_logger(monkeypatch):
    logger = MagicMock()
    monkeypatch.setattr(diag_module, "logger", logger)
    return logger


@pytest.fixture
def filenet_env(monkeypatch):
    monkeypatch.setenv("OPENRAG_FILENET_MCP_URL", MCP_URL)
    monkeypatch.delenv("OPENRAG_FILENET_MCP_TOKEN", raising=False)


def _response(status_code=200, json_data=None, json_error=None):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = json_data
    return response


def _client(*responses, side_effect=None):
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.side_effect = side_effect if side_effect is not None else list(responses)
    return client


def test_derive_admin_url():
    assert derive_admin_url(MCP_URL, "/health") == "http://filenet-mcp:8811/health"
    assert (
        derive_admin_url("https://host.example:9443/mcp/", "/diagnostics")
        == "https://host.example:9443/diagnostics"
    )


@pytest.mark.asyncio
async def test_no_url_configured_returns_none(monkeypatch, fake_logger):
    monkeypatch.delenv("OPENRAG_FILENET_MCP_URL", raising=False)
    result = await run_filenet_startup_diagnostics(http_client=_client())
    assert result is None
    fake_logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_healthy_sidecar_logs_info(filenet_env, fake_logger):
    client = _client(_response(200, {"status": "ok"}), _response(200, HEALTHY_PAYLOAD))
    result = await run_filenet_startup_diagnostics(http_client=client)

    assert result == HEALTHY_PAYLOAD
    fake_logger.warning.assert_not_called()
    info_messages = [call.args[0] for call in fake_logger.info.call_args_list]
    assert any("diagnostics passed" in m for m in info_messages)


@pytest.mark.asyncio
async def test_sidecar_unreachable_logs_warning_and_returns_none(filenet_env, fake_logger):
    client = _client(side_effect=httpx.ConnectError("refused"))
    result = await run_filenet_startup_diagnostics(http_client=client)

    assert result is None
    warning_messages = [call.args[0] for call in fake_logger.warning.call_args_list]
    assert any("unreachable" in m for m in warning_messages)


@pytest.mark.asyncio
async def test_health_non_200_logs_warning(filenet_env, fake_logger):
    client = _client(_response(503))
    result = await run_filenet_startup_diagnostics(http_client=client)

    assert result is None
    assert fake_logger.warning.called


@pytest.mark.asyncio
async def test_diagnostics_401_hints_at_token_mismatch(filenet_env, fake_logger):
    client = _client(_response(200, {"status": "ok"}), _response(401))
    result = await run_filenet_startup_diagnostics(http_client=client)

    assert result is None
    warning_messages = [call.args[0] for call in fake_logger.warning.call_args_list]
    assert any("OPENRAG_FILENET_MCP_TOKEN" in m for m in warning_messages)


@pytest.mark.asyncio
async def test_txe_missing_logs_metadata_only_warning(filenet_env, fake_logger):
    degraded = dict(HEALTHY_PAYLOAD, txe_annotation_class_present=False)
    client = _client(_response(200, {"status": "ok"}), _response(200, degraded))
    result = await run_filenet_startup_diagnostics(http_client=client)

    assert result == degraded
    warning_messages = [call.args[0] for call in fake_logger.warning.call_args_list]
    assert any("Persistent Text Extract" in m for m in warning_messages)
    assert any("metadata-only" in m for m in warning_messages)


@pytest.mark.asyncio
async def test_cpe_unreachable_from_sidecar_logs_warning(filenet_env, fake_logger):
    degraded = {
        "cpe_reachable": False,
        "txe_annotation_class_present": None,
        "cbr_enabled": None,
        "object_store": "FNOS1DS",
        "document_class": "Document",
        "errors": ["HTTP 401"],
    }
    client = _client(_response(200, {"status": "ok"}), _response(200, degraded))
    result = await run_filenet_startup_diagnostics(http_client=client)

    assert result == degraded
    warning_messages = [call.args[0] for call in fake_logger.warning.call_args_list]
    assert any("CPE GraphQL endpoint is not reachable" in m for m in warning_messages)


@pytest.mark.asyncio
async def test_cbr_disabled_logs_warning(filenet_env, fake_logger):
    degraded = dict(HEALTHY_PAYLOAD, cbr_enabled=False)
    client = _client(_response(200, {"status": "ok"}), _response(200, degraded))
    await run_filenet_startup_diagnostics(http_client=client)

    warning_messages = [call.args[0] for call in fake_logger.warning.call_args_list]
    assert any("CBR" in m for m in warning_messages)


@pytest.mark.asyncio
async def test_indeterminate_txe_logs_warning(filenet_env, fake_logger):
    degraded = dict(HEALTHY_PAYLOAD, txe_annotation_class_present=None)
    client = _client(_response(200, {"status": "ok"}), _response(200, degraded))
    await run_filenet_startup_diagnostics(http_client=client)

    warning_messages = [call.args[0] for call in fake_logger.warning.call_args_list]
    assert any("could not be determined" in m for m in warning_messages)


@pytest.mark.asyncio
async def test_bearer_token_sent_to_diagnostics_route(monkeypatch, fake_logger):
    monkeypatch.setenv("OPENRAG_FILENET_MCP_URL", MCP_URL)
    monkeypatch.setenv("OPENRAG_FILENET_MCP_TOKEN", "shared-secret")
    client = _client(_response(200, {"status": "ok"}), _response(200, HEALTHY_PAYLOAD))
    await run_filenet_startup_diagnostics(http_client=client)

    diag_call = client.get.call_args_list[1]
    assert diag_call.kwargs["headers"] == {"Authorization": "Bearer shared-secret"}


@pytest.mark.asyncio
async def test_non_json_diagnostics_body_never_raises(filenet_env, fake_logger):
    client = _client(
        _response(200, {"status": "ok"}), _response(200, json_error=ValueError("nope"))
    )
    result = await run_filenet_startup_diagnostics(http_client=client)
    assert result is None
    assert fake_logger.warning.called


@pytest.mark.asyncio
async def test_unexpected_exception_never_raises(filenet_env, fake_logger):
    client = _client(side_effect=RuntimeError("totally unexpected"))
    result = await run_filenet_startup_diagnostics(http_client=client)
    assert result is None
    assert fake_logger.warning.called
