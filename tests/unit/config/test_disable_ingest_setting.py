"""Unit tests for the disable_ingest_with_langflow configuration setting."""

import tempfile
from pathlib import Path

import pytest

from config.config_manager import ConfigManager


def test_disable_ingest_default(monkeypatch):
    """Verify that disable_ingest_with_langflow defaults to False when no env var is present."""
    monkeypatch.delenv("DISABLE_INGEST_WITH_LANGFLOW", raising=False)
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        config = cm.load_config()
        assert config.knowledge.disable_ingest_with_langflow is False


def test_disable_ingest_env_override(monkeypatch):
    """Verify that DISABLE_INGEST_WITH_LANGFLOW env var sets the default value of the setting."""
    monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "true")
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        config = cm.load_config()
        assert config.knowledge.disable_ingest_with_langflow is True

    monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "1")
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        config = cm.load_config()
        assert config.knowledge.disable_ingest_with_langflow is True

    monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "false")
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        config = cm.load_config()
        assert config.knowledge.disable_ingest_with_langflow is False


def test_disable_ingest_preserves_on_save(monkeypatch):
    """Verify that manual updates are persisted to yaml file and not overridden by env var on subsequent loads."""
    monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "false")
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        config = cm.load_config()
        assert config.knowledge.disable_ingest_with_langflow is False

        # Manually edit it to True
        config.knowledge.disable_ingest_with_langflow = True
        config.edited = True
        cm.save_config_file(config)

        # Reload configuration
        cm2 = ConfigManager(config_file=str(cfg_file))
        config2 = cm2.load_config()
        assert config2.knowledge.disable_ingest_with_langflow is True

        # Even if environment variable is set to False, once edited=True, the setting is preserved
        monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "false")
        config3 = cm2.load_config()
        assert config3.knowledge.disable_ingest_with_langflow is True


@pytest.mark.asyncio
async def test_traditional_upload_ingest_task(monkeypatch):
    """Verify that traditional ingestion invokes task_service.create_upload_task and returns 202."""
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import UploadFile

    from api.router import _traditional_upload_ingest_task
    from session_manager import User

    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "test_document.txt"
    mock_file.read = AsyncMock(return_value=b"Dummy content for traditional upload test")

    mock_task_service = MagicMock()
    mock_task_service.create_upload_task = AsyncMock(return_value="traditional-task-123")

    mock_session_manager = MagicMock()

    mock_user = MagicMock(spec=User)
    mock_user.user_id = "test-user-id"
    mock_user.name = "Test User"
    mock_user.email = "test@example.com"
    mock_user.jwt_token = "mock-jwt-token"

    # Mock _ensure_index_exists to avoid calling opensearch
    mock_ensure_index = AsyncMock()
    monkeypatch.setattr("api.documents._ensure_index_exists", mock_ensure_index)

    response = await _traditional_upload_ingest_task(
        upload_files=[mock_file],
        replace_duplicates=True,
        create_filter=False,
        session_manager=mock_session_manager,
        task_service=mock_task_service,
        user=mock_user,
    )

    assert response.status_code == 202
    import json

    data = json.loads(response.body.decode())
    assert data["task_id"] == "traditional-task-123"
    assert data["file_count"] == 1
    assert data["filename"] == "test_document.txt"

    mock_task_service.create_upload_task.assert_called_once()
    mock_ensure_index.assert_called_once_with("mock-jwt-token")
