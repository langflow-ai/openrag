"""Tests for flows_service flow updates: detecting them, and applying them with backups."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.flows_service import (  # noqa: E402
    FlowsService,
    flow_component_fingerprint,
    flow_signature,
)


@pytest.mark.asyncio
async def test_arbitrary_provider_uses_openai_compatible_langflow_component():
    service = FlowsService()
    update = AsyncMock(return_value={"flow": "retrieval", "success": True})

    with patch.object(service, "_update_provider_components", update):
        result = await service.change_langflow_model_value(
            "gemini",
            llm_model="gemini-2.5-pro",
            force_llm_update=True,
            flow_configs=[{"name": "retrieval", "flow_id": "flow-1"}],
        )

    assert result["success"] is True
    update.assert_awaited_once_with(
        {"name": "retrieval", "flow_id": "flow-1"},
        "openai",
        embedding_model=None,
        llm_model="gemini-2.5-pro",
        force_embedding_update=False,
        force_llm_update=True,
    )


@pytest.mark.asyncio
async def test_bulk_update_flows_creates_backup_flow_in_langflow():
    service = FlowsService()

    mock_get_response = MagicMock()
    mock_get_response.status_code = 200
    mock_get_response.json.return_value = {
        "id": "flow-retrieval-123",
        "name": "Custom Retrieval Flow",
        "locked": False,
        "data": {"nodes": []},
    }

    mock_post_response = MagicMock()
    mock_post_response.status_code = 201
    mock_post_response.json.return_value = {
        "id": "backup-flow-999",
        "name": "Backup - Custom Retrieval Flow (2026-07-23 20:00)",
    }

    async def mock_langflow_request(method, url, json=None, **kwargs):
        if method == "GET":
            return mock_get_response
        elif method == "POST":
            # Verify the posted backup payload
            assert "id" not in json
            assert json["name"].startswith("Backup - Custom Retrieval Flow")
            assert json["locked"] is False
            return mock_post_response
        return MagicMock(status_code=404)

    with (
        patch("services.flows_service.clients.langflow_request", side_effect=mock_langflow_request),
        patch.object(
            service, "_backup_flow", new_callable=AsyncMock, return_value="/tmp/backup.json"
        ),
        patch.object(
            service,
            "_reset_langflow_flow_locked",
            new_callable=AsyncMock,
            return_value={"success": True},
        ),
    ):
        results = await service.bulk_update_flows(["retrieval"], backup_custom=True)

    assert len(results) == 1
    res = results[0]
    assert res["flow_type"] == "retrieval"
    assert res["success"] is True
    assert res["backup_flow_id"] == "backup-flow-999"


@pytest.mark.asyncio
async def test_bulk_update_flows_aborts_reset_on_backup_failure():
    service = FlowsService()

    mock_get_response = MagicMock()
    mock_get_response.status_code = 200
    mock_get_response.json.return_value = {
        "id": "flow-retrieval-123",
        "name": "Custom Retrieval Flow",
        "locked": False,
        "data": {"nodes": []},
    }

    mock_post_response = MagicMock()
    mock_post_response.status_code = 500

    async def mock_langflow_request(method, url, json=None, **kwargs):
        if method == "GET":
            return mock_get_response
        elif method == "POST":
            return mock_post_response
        return MagicMock(status_code=404)

    reset_mock = AsyncMock(return_value={"success": True})

    with (
        patch("services.flows_service.clients.langflow_request", side_effect=mock_langflow_request),
        patch.object(service, "_backup_flow", new_callable=AsyncMock, return_value=None),
        patch.object(service, "_reset_langflow_flow_locked", reset_mock),
    ):
        results = await service.bulk_update_flows(["retrieval"], backup_custom=True)

    assert len(results) == 1
    res = results[0]
    assert res["flow_type"] == "retrieval"
    assert res["success"] is False
    assert "Backup failed" in res["error"]
    assert reset_mock.call_count == 0


@pytest.mark.asyncio
async def test_bulk_update_flows_saves_local_file_backup_for_default_flows():
    service = FlowsService()

    mock_get_response = MagicMock()
    mock_get_response.status_code = 200
    mock_get_response.json.return_value = {
        "id": "flow-retrieval-123",
        "name": "Default Retrieval Flow",
        "locked": True,
        "data": {"nodes": []},
    }

    backup_mock = AsyncMock(return_value="/tmp/backup_default.json")
    reset_mock = AsyncMock(return_value={"success": True})

    with (
        patch("services.flows_service.clients.langflow_request", return_value=mock_get_response),
        patch.object(service, "_backup_flow", backup_mock),
        patch.object(service, "_reset_langflow_flow_locked", reset_mock),
    ):
        results = await service.bulk_update_flows(["retrieval"], backup_custom=True)

    assert len(results) == 1
    assert results[0]["success"] is True
    assert backup_mock.call_count == 1
    assert reset_mock.call_count == 1


@pytest.mark.asyncio
async def test_bulk_update_flows_aborts_when_preflight_get_fails():
    """Verify issue (2a): pre-flight GET failure aborts update without attempting reset."""
    service = FlowsService()

    mock_get_response = MagicMock()
    mock_get_response.status_code = 500

    reset_mock = AsyncMock(return_value={"success": True})

    with (
        patch("services.flows_service.clients.langflow_request", return_value=mock_get_response),
        patch.object(service, "_reset_langflow_flow_locked", reset_mock),
    ):
        results = await service.bulk_update_flows(["retrieval"], backup_custom=True)

    assert len(results) == 1
    res = results[0]
    assert res["flow_type"] == "retrieval"
    assert res["success"] is False
    assert "Pre-flight check failed" in res["error"]
    assert reset_mock.call_count == 0


def test_per_user_dismissal_isolation():
    """Verify issue (2c): dismissal for user A does not dismiss for user B."""
    service = FlowsService()

    service.dismiss_flows_updates(["retrieval"], user_id="user_A")

    assert "user_A" in service._dismissed_updates
    assert "retrieval" in service._dismissed_updates["user_A"]
    assert (
        "user_B" not in service._dismissed_updates
        or "retrieval" not in service._dismissed_updates.get("user_B", set())
    )


@pytest.mark.asyncio
async def test_bulk_update_flows_dismissal_cleared_only_on_success():
    """Verify issue (4c): dismissal state is preserved on failure and cleared on success."""
    service = FlowsService()

    # Pre-dismiss update for user_A
    service.dismiss_flows_updates(["retrieval"], user_id="user_A")
    assert "retrieval" in service._dismissed_updates["user_A"]

    mock_get_fail = MagicMock(status_code=500)

    # 1. Update fails (pre-flight GET returns 500) -> dismissal remains intact
    with patch("services.flows_service.clients.langflow_request", return_value=mock_get_fail):
        results = await service.bulk_update_flows(["retrieval"], backup_custom=True)

    assert results[0]["success"] is False
    assert "retrieval" in service._dismissed_updates.get("user_A", set())

    # 2. Update succeeds -> dismissal is cleared
    mock_get_ok = MagicMock(status_code=200)
    mock_get_ok.json.return_value = {
        "id": "flow-retrieval-123",
        "name": "Retrieval Flow",
        "locked": True,
        "data": {"nodes": []},
    }

    with (
        patch("services.flows_service.clients.langflow_request", return_value=mock_get_ok),
        patch.object(service, "_backup_flow", AsyncMock(return_value="/tmp/backup.json")),
        patch.object(
            service, "_reset_langflow_flow_locked", AsyncMock(return_value={"success": True})
        ),
    ):
        results = await service.bulk_update_flows(["retrieval"], backup_custom=True)

    assert results[0]["success"] is True
    assert "retrieval" not in service._dismissed_updates.get("user_A", set())


@pytest.mark.asyncio
async def test_ensure_flows_exist_does_not_auto_update_on_startup():
    """Verify that existing flows are skipped on startup and never auto-updated."""
    service = FlowsService()

    mock_get_ok = MagicMock(status_code=200)
    mock_get_ok.json.return_value = {
        "id": "flow-retrieval-123",
        "name": "Retrieval Flow",
        "locked": True,
        "updated_at": "2020-01-01T00:00:00Z",
    }

    reset_mock = AsyncMock()
    backup_mock = AsyncMock()

    with (
        patch("services.flows_service.clients.langflow_request", return_value=mock_get_ok),
        patch.object(service, "_backup_flow", backup_mock),
        patch.object(service, "_reset_langflow_flow_locked", reset_mock),
    ):
        created = await service.ensure_flows_exist()

    assert created == set()
    assert backup_mock.call_count == 0
    assert reset_mock.call_count == 0


@pytest.mark.asyncio
async def test_get_flows_updates_available_includes_all_flows():
    """Verify that get_flows_updates_available surfaces updates regardless of locked status."""
    service = FlowsService()

    mock_update_info = {
        "flow_type": "retrieval",
        "flow_id": "flow-retrieval-123",
        "is_custom": False,
    }

    with patch.object(service, "_check_flow_update", AsyncMock(return_value=mock_update_info)):
        updates = await service.get_flows_updates_available()

    assert len(updates) == 4
    assert all(u["flow_type"] in ["nudges", "retrieval", "ingest", "url_ingest"] for u in updates)


def _shipped_flow(code_hash: str = "aaa111", chunk_size: int = 1000) -> dict:
    return {
        "id": "flow-ingest-1",
        "name": "OpenRAG Ingest",
        "data": {
            "nodes": [
                {
                    "id": "SplitText-1",
                    "data": {
                        "type": "OpenRAGSplitText",
                        "node": {
                            "metadata": {"module": "openrag.split_text", "code_hash": code_hash},
                            "template": {"chunk_size": {"value": chunk_size}},
                        },
                    },
                }
            ],
            "edges": [
                {
                    "source": "SplitText-1",
                    "target": "OpenSearch-1",
                    "data": {
                        "sourceHandle": {"name": "dataframe"},
                        "targetHandle": {"fieldName": "ingest_data"},
                    },
                }
            ],
        },
    }


def _langflow_copy(flow: dict, **fields) -> dict:
    return {**flow, "locked": True, "updated_at": "2999-01-01T00:00:00Z", **fields}


@pytest.fixture
def update_check(tmp_path):
    """Run _check_flow_update against a shipped file and a recorded signature."""
    from config.config_manager import FlowsState

    async def run(shipped: dict, langflow: dict, recorded: str | None):
        flow_file = tmp_path / "ingestion_flow.json"
        flow_file.write_text(json.dumps(shipped), encoding="utf-8")
        signatures = {"ingest": recorded} if recorded is not None else {}
        config = SimpleNamespace(flows=FlowsState(applied_signatures=signatures))
        response = MagicMock(status_code=200)
        response.json.return_value = langflow
        request = AsyncMock(return_value=response)
        record = MagicMock()
        service = FlowsService()
        with (
            patch.object(service, "_find_flow_file_by_id", return_value=str(flow_file)),
            patch("services.flows_service.get_openrag_config", return_value=config),
            patch("services.flows_service.clients.langflow_request", request),
            patch("services.flows_service.record_applied_flow_signatures", record),
        ):
            result = await service._check_flow_update("ingest", "flow-ingest-1")
        return result, request, record

    return run


@pytest.mark.asyncio
async def test_update_check_is_quiet_when_shipped_flow_was_already_applied(update_check):
    shipped = _shipped_flow()

    result, request, record = await update_check(
        shipped, _langflow_copy(shipped), recorded=flow_signature(shipped)
    )

    assert result is None
    request.assert_not_called()
    record.assert_not_called()


@pytest.mark.asyncio
async def test_update_check_reports_new_shipped_flow_even_if_langflow_copy_is_newer(update_check):
    """A settings save after the release was built must not hide the update."""
    old = _shipped_flow(code_hash="old000")
    new = _shipped_flow(code_hash="new999")

    result, _, record = await update_check(
        new, _langflow_copy(old, locked=False), recorded=flow_signature(old)
    )

    assert result == {"flow_type": "ingest", "flow_id": "flow-ingest-1", "is_custom": True}
    record.assert_not_called()


@pytest.mark.asyncio
async def test_update_check_adopts_matching_flow_on_installs_without_a_signature(update_check):
    shipped = _shipped_flow(chunk_size=1000)
    # The user's chunk size was written into Langflow's copy; components are the same.
    running = _langflow_copy(_shipped_flow(chunk_size=500))

    result, _, record = await update_check(shipped, running, recorded=None)

    assert result is None
    record.assert_called_once_with({"ingest": flow_signature(shipped)})


@pytest.mark.asyncio
async def test_update_check_reports_changed_component_on_installs_without_a_signature(
    update_check,
):
    shipped = _shipped_flow(code_hash="new999")
    running = _langflow_copy(_shipped_flow(code_hash="old000"))

    result, _, record = await update_check(shipped, running, recorded=None)

    assert result == {"flow_type": "ingest", "flow_id": "flow-ingest-1", "is_custom": False}
    record.assert_not_called()


def test_component_fingerprint_ignores_field_values_but_not_code():
    base = flow_component_fingerprint(_shipped_flow())

    assert flow_component_fingerprint(_shipped_flow(chunk_size=250)) == base
    assert flow_component_fingerprint(_shipped_flow(code_hash="other")) != base


@pytest.mark.asyncio
async def test_reset_records_the_signature_of_the_flow_it_wrote(tmp_path):
    shipped = _shipped_flow()
    flow_file = tmp_path / "ingestion_flow.json"
    flow_file.write_text(json.dumps(shipped), encoding="utf-8")
    service = FlowsService()
    patch_response = MagicMock(status_code=200)
    patch_response.json.return_value = {"folder_id": None}
    record = MagicMock()

    with (
        patch("services.flows_service.LANGFLOW_URL", "http://langflow:7860"),
        patch.object(service, "_find_flow_file_by_id", return_value=str(flow_file)),
        patch.object(service, "_unlock_flow", AsyncMock()),
        patch.object(service, "_lock_flow", AsyncMock()),
        patch(
            "services.flows_service.clients.langflow_request",
            AsyncMock(return_value=patch_response),
        ),
        patch("services.flows_service.record_applied_flow_signatures", record),
    ):
        result = await service._reset_langflow_flow_locked("ingest", "flow-ingest-1")

    assert result["success"] is True
    record.assert_called_once_with({"ingest": flow_signature(shipped)})


@pytest.mark.asyncio
async def test_ensure_flows_exist_records_signatures_of_created_flows(tmp_path):
    shipped = _shipped_flow()
    flow_file = tmp_path / "ingestion_flow.json"
    flow_file.write_text(json.dumps(shipped), encoding="utf-8")
    service = FlowsService()

    async def langflow_request(method, url, **kwargs):
        if method == "GET":
            return MagicMock(status_code=404)
        created = MagicMock(status_code=201)
        created.json.return_value = {"folder_id": None}
        return created

    record = MagicMock()
    with (
        patch("services.flows_service.NUDGES_FLOW_ID", None),
        patch("services.flows_service.LANGFLOW_CHAT_FLOW_ID", None),
        patch("services.flows_service.LANGFLOW_URL_INGEST_FLOW_ID", None),
        patch("services.flows_service.LANGFLOW_INGEST_FLOW_ID", "flow-ingest-1"),
        patch.object(service, "_find_flow_file_by_id", return_value=str(flow_file)),
        patch("services.flows_service.clients.langflow_request", side_effect=langflow_request),
        patch("services.flows_service.record_applied_flow_signatures", record),
        patch(
            "services.flows_service.get_openrag_config",
            return_value=SimpleNamespace(edited=False),
        ),
    ):
        created = await service.ensure_flows_exist()

    assert created == {"ingest"}
    record.assert_called_once_with({"ingest": flow_signature(shipped)})
