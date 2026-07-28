"""Tests for OSS stock-flow refresh on OpenRAG version upgrade."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.flows_service import FlowsService


def _config(*, flows_synced_version: str | None = None, edited: bool = False):
    return SimpleNamespace(
        edited=edited,
        onboarding=SimpleNamespace(openrag_flows_synced_version=flows_synced_version),
    )


@pytest.mark.asyncio
async def test_refresh_noop_when_version_matches(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    service = FlowsService()
    config = _config(flows_synced_version="0.6.0")

    with (
        patch("services.flows_service.get_openrag_config", return_value=config),
        patch("services.flows_service.OPENRAG_VERSION", "0.6.0"),
        patch.object(service, "_refresh_unlocked_stock_flow", new_callable=AsyncMock) as refresh,
    ):
        refreshed = await service.refresh_stock_flows_on_upgrade_if_needed(newly_created=set())

    assert refreshed == set()
    refresh.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_skips_non_oss(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    service = FlowsService()
    config = _config(flows_synced_version="0.5.1")

    with (
        patch("services.flows_service.get_openrag_config", return_value=config),
        patch("services.flows_service.OPENRAG_VERSION", "0.6.0"),
        patch.object(service, "_refresh_unlocked_stock_flow", new_callable=AsyncMock) as refresh,
    ):
        refreshed = await service.refresh_stock_flows_on_upgrade_if_needed(newly_created=set())

    assert refreshed == set()
    refresh.assert_not_called()


@pytest.mark.asyncio
async def test_fresh_install_stamps_without_patch(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    service = FlowsService()
    config = _config(flows_synced_version=None)
    save = MagicMock(return_value=True)

    with (
        patch("services.flows_service.get_openrag_config", return_value=config),
        patch("services.flows_service.OPENRAG_VERSION", "0.6.0"),
        patch("config.config_manager.config_manager.save_config_file", save),
        patch.object(service, "_refresh_unlocked_stock_flow", new_callable=AsyncMock) as refresh,
    ):
        refreshed = await service.refresh_stock_flows_on_upgrade_if_needed(
            newly_created={"ingest", "retrieval", "nudges", "url_ingest"}
        )

    assert refreshed == set()
    refresh.assert_not_called()
    assert config.onboarding.openrag_flows_synced_version == "0.6.0"
    save.assert_called_once_with(config, preserve_edited=True)
    assert config.edited is False


@pytest.mark.asyncio
async def test_upgrade_refreshes_unlocked_ingest(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    service = FlowsService()
    config = _config(flows_synced_version="0.5.1")
    save = MagicMock(return_value=True)

    async def _refresh(flow_type, flow_id):
        return "refreshed" if flow_type == "ingest" else "skipped_locked"

    with (
        patch("services.flows_service.get_openrag_config", return_value=config),
        patch("services.flows_service.OPENRAG_VERSION", "0.6.0"),
        patch("config.config_manager.config_manager.save_config_file", save),
        patch.object(
            service, "_refresh_unlocked_stock_flow", new_callable=AsyncMock, side_effect=_refresh
        ) as refresh,
        patch("services.flows_service.LANGFLOW_INGEST_FLOW_ID", "ingest-id"),
        patch("services.flows_service.LANGFLOW_CHAT_FLOW_ID", "chat-id"),
        patch("services.flows_service.NUDGES_FLOW_ID", "nudges-id"),
        patch("services.flows_service.LANGFLOW_URL_INGEST_FLOW_ID", "url-id"),
    ):
        refreshed = await service.refresh_stock_flows_on_upgrade_if_needed(newly_created=set())

    assert refreshed == {"ingest"}
    assert refresh.await_count == 4
    assert config.onboarding.openrag_flows_synced_version == "0.6.0"
    save.assert_called_once_with(config, preserve_edited=True)


@pytest.mark.asyncio
async def test_pre_stamp_upgrade_when_ingest_already_existed(monkeypatch):
    """0.5.1 installs have no stamp; existing ingest means upgrade, not fresh create."""
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    service = FlowsService()
    config = _config(flows_synced_version=None)
    save = MagicMock(return_value=True)

    with (
        patch("services.flows_service.get_openrag_config", return_value=config),
        patch("services.flows_service.OPENRAG_VERSION", "0.6.0"),
        patch("config.config_manager.config_manager.save_config_file", save),
        patch.object(
            service,
            "_refresh_unlocked_stock_flow",
            new_callable=AsyncMock,
            return_value="refreshed",
        ) as refresh,
        patch("services.flows_service.LANGFLOW_INGEST_FLOW_ID", "ingest-id"),
        patch("services.flows_service.LANGFLOW_CHAT_FLOW_ID", None),
        patch("services.flows_service.NUDGES_FLOW_ID", None),
        patch("services.flows_service.LANGFLOW_URL_INGEST_FLOW_ID", None),
    ):
        refreshed = await service.refresh_stock_flows_on_upgrade_if_needed(newly_created=set())

    assert refreshed == {"ingest"}
    refresh.assert_awaited_once()
    save.assert_called_once_with(config, preserve_edited=True)


@pytest.mark.asyncio
async def test_refresh_unlocked_skips_locked_flow():
    service = FlowsService()
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"id": "ingest-id", "locked": True}

    with patch(
        "services.flows_service.clients.langflow_request",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ) as request:
        result = await service._refresh_unlocked_stock_flow("ingest", "ingest-id")

    assert result == "skipped_locked"
    request.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_unlocked_patches_from_bundle(tmp_path):
    service = FlowsService()
    flow_id = "5488df7c-b93f-4f87-a446-b67028bc0813"
    flow_file = tmp_path / "ingestion_flow.json"
    flow_payload = {"id": flow_id, "name": "OpenSearch Ingestion Flow", "data": {}}
    flow_file.write_text(json.dumps(flow_payload))

    get_resp = MagicMock(status_code=200)
    get_resp.json.return_value = {"id": flow_id, "locked": False}
    patch_resp = MagicMock(status_code=200, text="ok")

    async def _request(method, path, **kwargs):
        if method == "GET":
            return get_resp
        return patch_resp

    with (
        patch(
            "services.flows_service.clients.langflow_request",
            new_callable=AsyncMock,
            side_effect=_request,
        ),
        patch.object(service, "_find_flow_file_by_id", return_value=str(flow_file)),
    ):
        result = await service._refresh_unlocked_stock_flow("ingest", flow_id)

    assert result == "refreshed"
