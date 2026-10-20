"""Tests for flows_service bulk_update_flows with Langflow backup creation."""

import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.flows_service import FlowsService  # noqa: E402

FLOW_TAG_SCRIPT_PATH = ROOT / "scripts" / "tag_flow_version.py"
FLOW_TAG_SCRIPT_SPEC = spec_from_file_location("tag_flow_version", FLOW_TAG_SCRIPT_PATH)
assert FLOW_TAG_SCRIPT_SPEC and FLOW_TAG_SCRIPT_SPEC.loader
flow_tag_version = module_from_spec(FLOW_TAG_SCRIPT_SPEC)
FLOW_TAG_SCRIPT_SPEC.loader.exec_module(flow_tag_version)


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


@pytest.mark.asyncio
async def test_flow_update_requires_a_newer_version_and_different_content_id(tmp_path, monkeypatch):
    service = FlowsService()
    flow_path = tmp_path / "flow.json"
    flow_path.write_text(
        '{"id": "flow-1", "tags": ["openrag:flow-version:2.0.0:new-id"]}',
        encoding="utf-8",
    )

    monkeypatch.setenv("OPENRAG_IMAGE_FLOWS_PATH", str(tmp_path))
    with patch.object(
        service, "_find_flow_file_by_id", return_value=str(flow_path)
    ) as find_flow_file:
        update = await service._check_flow_update(
            "retrieval",
            "flow-1",
            {
                "locked": True,
                "tags": ["openrag:flow-version:1.9.0:old-id"],
                "updated_at": "2099-01-01T00:00:00Z",
            },
        )

    find_flow_file.assert_called_once_with("flow-1", str(tmp_path))
    assert update == {"flow_type": "retrieval", "flow_id": "flow-1", "is_custom": False}


@pytest.mark.asyncio
async def test_flow_update_ignores_timestamp_when_version_or_content_id_do_not_require_upgrade(tmp_path):
    service = FlowsService()
    flow_path = tmp_path / "flow.json"
    flow_path.write_text(
        '{"id": "flow-1", "tags": ["openrag:flow-version:2.0.0:matching-id"]}',
        encoding="utf-8",
    )

    with patch.object(service, "_find_flow_file_by_id", return_value=str(flow_path)):
        update = await service._check_flow_update(
            "retrieval",
            "flow-1",
            {
                "locked": False,
                "tags": ["openrag:flow-version:1.0.0:matching-id"],
                "updated_at": "1970-01-01T00:00:00Z",
            },
        )

    assert update is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored_tag",
    [
        "openrag:flow-version:2.0.0:old-id",
        "openrag:flow-version:3.0.0:old-id",
    ],
)
async def test_flow_update_does_not_upgrade_without_a_larger_version(tmp_path, stored_tag):
    service = FlowsService()
    flow_path = tmp_path / "flow.json"
    flow_path.write_text(
        '{"id": "flow-1", "tags": ["openrag:flow-version:2.0.0:new-id"]}',
        encoding="utf-8",
    )

    with patch.object(service, "_find_flow_file_by_id", return_value=str(flow_path)):
        update = await service._check_flow_update("retrieval", "flow-1", {"tags": [stored_tag]})

    assert update is None


@pytest.mark.asyncio
async def test_flow_update_detects_legacy_stored_flow_without_a_release_tag(tmp_path):
    service = FlowsService()
    flow_path = tmp_path / "flow.json"
    flow_path.write_text(
        '{"id": "flow-1", "tags": ["openrag:flow-version:2.0.0:image-id"]}',
        encoding="utf-8",
    )

    with patch.object(service, "_find_flow_file_by_id", return_value=str(flow_path)):
        update = await service._check_flow_update(
            "retrieval", "flow-1", {"locked": False, "tags": ["rag"]}
        )

    assert update == {"flow_type": "retrieval", "flow_id": "flow-1", "is_custom": True}


@pytest.mark.asyncio
async def test_flow_update_requires_a_release_tag_on_the_bundled_flow(tmp_path):
    service = FlowsService()
    flow_path = tmp_path / "flow.json"
    flow_path.write_text('{"id": "flow-1", "tags": ["rag"]}', encoding="utf-8")

    with patch.object(service, "_find_flow_file_by_id", return_value=str(flow_path)):
        update = await service._check_flow_update(
            "retrieval", "flow-1", {"tags": ["openrag:flow-version:1.0.0:old-id"]}
        )

    assert update is None


def test_stamp_flow_version_tags_replaces_previous_release_tag(tmp_path):
    flow_path = tmp_path / "flow.json"
    component_index_path = tmp_path / "component_index.json"
    pyproject_path = tmp_path / "pyproject.toml"
    flow_path.write_text(
        '{"id": "flow-1", "tags": ["rag", "openrag:flow-version:1.0.0:old-id"]}',
        encoding="utf-8",
    )
    component_index_path.write_text('[]', encoding="utf-8")
    pyproject_path.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    updated_paths = flow_tag_version.stamp_flow_version_tags(tmp_path, pyproject_path)

    assert updated_paths == [flow_path]
    assert component_index_path.read_text(encoding="utf-8") == "[]"
    tags = json.loads(flow_path.read_text(encoding="utf-8"))["tags"]
    assert tags[:1] == ["rag"]
    assert tags[1].startswith("openrag:flow-version:1.2.3:")
    assert len(tags[1].rsplit(":", 1)[1]) == 12


def test_stamp_flow_version_tags_rejects_invalid_flow_tags(tmp_path):
    flow_path = tmp_path / "flow.json"
    pyproject_path = tmp_path / "pyproject.toml"
    flow_path.write_text('{"id": "flow-1", "tags": "not-a-list"}', encoding="utf-8")
    pyproject_path.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="invalid flow tags"):
        flow_tag_version.stamp_flow_version_tags(tmp_path, pyproject_path)
