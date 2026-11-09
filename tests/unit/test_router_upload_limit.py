"""Oversized uploads are refused before a task is created."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from api.router import _langflow_upload_ingest_task, _traditional_upload_ingest_task
from session_manager import User


def _user() -> User:
    return User(user_id="user-1", email="u@example.com", name="User", jwt_token="Bearer tok")


def _file(filename: str, content: bytes) -> MagicMock:
    upload = MagicMock(spec=UploadFile)
    upload.filename = filename
    upload.content_type = "application/pdf"
    upload.size = None
    upload.read = AsyncMock(side_effect=[content, b""])
    return upload


@pytest.mark.asyncio
async def test_langflow_upload_rejects_oversized_file_before_creating_a_task(monkeypatch):
    monkeypatch.setattr("config.settings.OPENRAG_MAX_UPLOAD_MB", 1)
    task_service = MagicMock()
    task_service.create_langflow_upload_task = AsyncMock(return_value="task-1")

    response = await _langflow_upload_ingest_task(
        upload_files=[_file("big.pdf", b"x" * (1024 * 1024 + 1))],
        session_id=None,
        settings_json=None,
        tweaks_json=None,
        replace_duplicates=True,
        create_filter=False,
        preview_mode=False,
        langflow_file_service=MagicMock(),
        session_manager=MagicMock(),
        task_service=task_service,
        user=_user(),
        allow_anonymous_delete=False,
    )

    assert response.status_code == 413
    body = json.loads(response.body.decode())
    assert "big.pdf" in body["error"]
    assert "OPENRAG_MAX_UPLOAD_MB" in body["error"]
    task_service.create_langflow_upload_task.assert_not_called()


@pytest.mark.asyncio
async def test_langflow_upload_rejects_declared_size_without_reading(monkeypatch):
    monkeypatch.setattr("config.settings.OPENRAG_MAX_UPLOAD_MB", 1)
    upload = _file("big.pdf", b"")
    upload.size = 2 * 1024 * 1024
    upload.read = AsyncMock()
    task_service = MagicMock()
    task_service.create_langflow_upload_task = AsyncMock(return_value="task-1")

    response = await _langflow_upload_ingest_task(
        upload_files=[upload],
        session_id=None,
        settings_json=None,
        tweaks_json=None,
        replace_duplicates=True,
        create_filter=False,
        preview_mode=False,
        langflow_file_service=MagicMock(),
        session_manager=MagicMock(),
        task_service=task_service,
        user=_user(),
        allow_anonymous_delete=False,
    )

    assert response.status_code == 413
    upload.read.assert_not_called()
    task_service.create_langflow_upload_task.assert_not_called()


@pytest.mark.asyncio
async def test_langflow_upload_accepts_a_file_under_the_limit():
    task_service = MagicMock()
    task_service.create_langflow_upload_task = AsyncMock(return_value="task-1")
    mock_temp_file = MagicMock()
    mock_temp_file.name = "/tmp/small.pdf"

    with (
        patch("api.router.tempfile.NamedTemporaryFile", return_value=mock_temp_file),
        patch("api.router.open", create=True),
        patch("utils.file_utils.safe_unlink"),
    ):
        response = await _langflow_upload_ingest_task(
            upload_files=[_file("small.pdf", b"%PDF")],
            session_id=None,
            settings_json=None,
            tweaks_json=None,
            replace_duplicates=True,
            create_filter=False,
            preview_mode=False,
            langflow_file_service=MagicMock(),
            session_manager=MagicMock(),
            task_service=task_service,
            user=_user(),
            allow_anonymous_delete=False,
        )

    assert response.status_code == 202
    task_service.create_langflow_upload_task.assert_awaited()


@pytest.mark.asyncio
async def test_traditional_upload_rejects_oversized_file_before_creating_a_task(monkeypatch):
    monkeypatch.setattr("config.settings.OPENRAG_MAX_UPLOAD_MB", 1)
    task_service = MagicMock()
    task_service.create_upload_task = AsyncMock(return_value="task-1")

    response = await _traditional_upload_ingest_task(
        upload_files=[_file("big.pdf", b"x" * (1024 * 1024 + 1))],
        replace_duplicates=True,
        create_filter=False,
        preview_mode=False,
        session_manager=MagicMock(),
        task_service=task_service,
        user=_user(),
        allow_anonymous_delete=False,
    )

    assert response.status_code == 413
    body = json.loads(response.body.decode())
    assert "big.pdf" in body["error"]
    task_service.create_upload_task.assert_not_called()
