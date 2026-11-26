"""Tests for Langflow initialization shared by startup and live re-enable."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import startup_orchestrator


@pytest.mark.asyncio
async def test_strict_initialization_prepares_flows_before_reenable(monkeypatch):
    config = SimpleNamespace(disable_langflow=False, langflow_sync_pending=True)
    flows_service = MagicMock(
        ensure_flows_exist=AsyncMock(), verify_configured_flows_exist=AsyncMock()
    )
    wait_for_langflow = AsyncMock()
    ensure_variables = AsyncMock()
    reapply = AsyncMock(return_value=True)
    http_client = object()

    monkeypatch.setattr(startup_orchestrator, "is_langflow_disabled", lambda _config: False)
    monkeypatch.setattr(
        startup_orchestrator.clients,
        "_ensure_langflow_http_client",
        MagicMock(return_value=http_client),
    )
    monkeypatch.setattr("utils.langflow_utils.wait_for_langflow", wait_for_langflow)
    monkeypatch.setattr(
        "api.settings.langflow_sync.ensure_required_langflow_global_variables",
        ensure_variables,
    )
    monkeypatch.setattr("api.settings.langflow_sync.reapply_all_settings", reapply)

    await startup_orchestrator.initialize_langflow_services(
        {"flows_service": flows_service},
        config=config,
        session_manager="session",
        strict=True,
    )

    wait_for_langflow.assert_awaited_once_with(http_client)
    flows_service.ensure_flows_exist.assert_awaited_once()
    flows_service.verify_configured_flows_exist.assert_awaited_once()
    ensure_variables.assert_awaited_once_with(config)
    reapply.assert_awaited_once_with(session_manager="session", config=config)
    assert config.langflow_sync_pending is False


@pytest.mark.asyncio
async def test_strict_initialization_fails_before_traffic_switch(monkeypatch):
    config = SimpleNamespace(disable_langflow=False, langflow_sync_pending=True)
    flows_service = MagicMock(
        ensure_flows_exist=AsyncMock(),
        verify_configured_flows_exist=AsyncMock(side_effect=RuntimeError("ingest flow missing")),
    )

    monkeypatch.setattr(startup_orchestrator, "is_langflow_disabled", lambda _config: False)
    monkeypatch.setattr(
        startup_orchestrator.clients,
        "_ensure_langflow_http_client",
        MagicMock(return_value=object()),
    )
    monkeypatch.setattr("utils.langflow_utils.wait_for_langflow", AsyncMock())

    with pytest.raises(RuntimeError, match="ingest flow missing"):
        await startup_orchestrator.initialize_langflow_services(
            {"flows_service": flows_service}, config=config, strict=True
        )

    assert config.langflow_sync_pending is True
