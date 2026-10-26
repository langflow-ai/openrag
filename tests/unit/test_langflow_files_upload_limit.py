"""The Langflow file routes refuse an oversized upload before doing any work."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from api.langflow_files import upload_and_ingest_user_file, upload_user_file
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


def _error(response) -> str:
    return json.loads(response.body.decode())["error"]


@pytest.mark.asyncio
async def test_langflow_file_upload_rejects_an_oversized_file_before_posting(monkeypatch):
    monkeypatch.setattr("config.settings.OPENRAG_MAX_UPLOAD_MB", 1)
    service = MagicMock()
    service.upload_user_file = AsyncMock()

    response = await upload_user_file(
        file=_file("big.pdf", b"x" * (1024 * 1024 + 1)),
        langflow_file_service=service,
        user=_user(),
    )

    assert response.status_code == 413
    assert "big.pdf" in _error(response)
    assert "OPENRAG_MAX_UPLOAD_MB" in _error(response)
    service.upload_user_file.assert_not_called()


@pytest.mark.asyncio
async def test_langflow_file_upload_rejects_a_declared_size_without_reading(monkeypatch):
    monkeypatch.setattr("config.settings.OPENRAG_MAX_UPLOAD_MB", 1)
    upload = _file("big.pdf", b"")
    upload.size = 2 * 1024 * 1024
    upload.read = AsyncMock()
    service = MagicMock()
    service.upload_user_file = AsyncMock()

    response = await upload_user_file(file=upload, langflow_file_service=service, user=_user())

    assert response.status_code == 413
    upload.read.assert_not_called()
    service.upload_user_file.assert_not_called()


@pytest.mark.asyncio
async def test_langflow_upload_ingest_rejects_an_oversized_file_before_a_task(monkeypatch):
    monkeypatch.setattr("config.settings.OPENRAG_MAX_UPLOAD_MB", 1)
    task_service = MagicMock()
    task_service.create_langflow_upload_task = AsyncMock(return_value="task-1")

    response = await upload_and_ingest_user_file(
        file=_file("big.pdf", b"x" * (1024 * 1024 + 1)),
        session_id=None,
        settings_json=None,
        tweaks_json=None,
        langflow_file_service=MagicMock(),
        session_manager=MagicMock(),
        task_service=task_service,
        user=_user(),
    )

    assert response.status_code == 413
    assert "big.pdf" in _error(response)
    task_service.create_langflow_upload_task.assert_not_called()


@pytest.mark.asyncio
async def test_langflow_upload_ingest_rejects_a_declared_size_without_reading(monkeypatch):
    monkeypatch.setattr("config.settings.OPENRAG_MAX_UPLOAD_MB", 1)
    upload = _file("big.pdf", b"")
    upload.size = 2 * 1024 * 1024
    upload.read = AsyncMock()
    task_service = MagicMock()
    task_service.create_langflow_upload_task = AsyncMock(return_value="task-1")

    response = await upload_and_ingest_user_file(
        file=upload,
        session_id=None,
        settings_json=None,
        tweaks_json=None,
        langflow_file_service=MagicMock(),
        session_manager=MagicMock(),
        task_service=task_service,
        user=_user(),
    )

    assert response.status_code == 413
    upload.read.assert_not_called()
    task_service.create_langflow_upload_task.assert_not_called()
