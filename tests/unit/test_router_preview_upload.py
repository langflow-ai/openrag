"""Tests that preview=true is threaded through the upload router."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from api.router import _langflow_upload_ingest_task, upload_ingest_router
from session_manager import User


@pytest.mark.asyncio
async def test_langflow_upload_passes_preview_mode_to_task_service():
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "sample.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"%PDF-sample")

    mock_task_service = MagicMock()
    mock_task_service.create_langflow_upload_task = AsyncMock(return_value="task-preview-1")

    user = User(user_id="user-1", email="u@example.com", name="User", jwt_token="Bearer tok")

    mock_temp_file = MagicMock()
    mock_temp_file.name = "/tmp/sample.pdf"

    with (
        patch("api.router.tempfile.NamedTemporaryFile", return_value=mock_temp_file),
        patch("api.router.open", create=True),
        patch("utils.file_utils.safe_unlink"),
        patch("api.router.is_ingest_preview_enabled", return_value=True),
    ):
        response = await _langflow_upload_ingest_task(
            upload_files=[mock_file],
            session_id=None,
            settings_json=None,
            tweaks_json=None,
            replace_duplicates=True,
            create_filter=False,
            preview_mode=True,
            langflow_file_service=MagicMock(),
            session_manager=MagicMock(),
            task_service=mock_task_service,
            user=user,
        )

    assert response.status_code == 202
    call_kwargs = mock_task_service.create_langflow_upload_task.await_args.kwargs
    assert call_kwargs["preview_mode"] is True

    import json

    body = json.loads(response.body.decode())
    assert body["preview_mode"] is True


@pytest.mark.asyncio
async def test_upload_ingest_router_ignores_preview_when_disabled():
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "sample.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"%PDF-sample")

    mock_task_service = MagicMock()
    mock_task_service.create_langflow_upload_task = AsyncMock(return_value="task-1")

    user = User(user_id="user-1", email="u@example.com", name="User", jwt_token="Bearer tok")

    mock_temp_file = MagicMock()
    mock_temp_file.name = "/tmp/sample.pdf"

    with (
        patch("api.router.get_openrag_config") as mock_cfg,
        patch("api.router.tempfile.NamedTemporaryFile", return_value=mock_temp_file),
        patch("api.router.open", create=True),
        patch("utils.file_utils.safe_unlink"),
        patch("api.router.is_ingest_preview_enabled", return_value=False),
    ):
        mock_cfg.return_value.knowledge.disable_ingest_with_langflow = False

        response = await upload_ingest_router(
            file=[mock_file],
            session_id=None,
            settings_json=None,
            tweaks_json=None,
            preview="true",
            replace_duplicates="true",
            create_filter="false",
            langflow_file_service=MagicMock(),
            session_manager=MagicMock(),
            task_service=mock_task_service,
            document_service=MagicMock(),
            user=user,
        )

    assert response.status_code == 202
    call_kwargs = mock_task_service.create_langflow_upload_task.await_args.kwargs
    assert call_kwargs["preview_mode"] is False
