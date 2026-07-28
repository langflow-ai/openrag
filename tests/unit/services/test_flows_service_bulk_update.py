"""Tests for flows_service bulk_update_flows with Langflow backup creation."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.flows_service import FlowsService  # noqa: E402


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
