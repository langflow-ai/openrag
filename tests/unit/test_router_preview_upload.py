"""Tests that preview=true is threaded through the upload router."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from api.router import (
    _langflow_upload_ingest_task,
    _normalize_source_urls,
    _resolve_archive_source,
    upload_ingest_router,
)
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
            source_urls=["https://files.example.com/sample.pdf"],
            archive_sources=True,
            langflow_file_service=MagicMock(),
            session_manager=MagicMock(),
            task_service=mock_task_service,
            user=user,
        )

    assert response.status_code == 202
    call_kwargs = mock_task_service.create_langflow_upload_task.await_args.kwargs
    assert call_kwargs["preview_mode"] is True
    assert call_kwargs["source_urls"] == {"/tmp/sample.pdf": "https://files.example.com/sample.pdf"}
    assert call_kwargs["archive_sources"] is True

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
        patch("config.settings.is_no_auth_mode", return_value=True),
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
            archive_source="true",
            langflow_file_service=MagicMock(),
            session_manager=MagicMock(),
            task_service=mock_task_service,
            document_service=MagicMock(),
            user=user,
        )

    assert response.status_code == 202
    call_kwargs = mock_task_service.create_langflow_upload_task.await_args.kwargs
    assert call_kwargs["preview_mode"] is False
    assert call_kwargs["archive_sources"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_urls", "expected_source_urls"),
    [
        (None, {}),
        (
            ["https://archive.example.com/original.pdf"],
            {"/tmp/sample.pdf": "https://archive.example.com/original.pdf"},
        ),
    ],
)
@pytest.mark.parametrize(
    ("disable_langflow_ingest", "task_method"),
    [
        (False, "create_langflow_upload_task"),
        (True, "create_upload_task"),
    ],
)
async def test_multi_user_upload_remains_available_without_local_archiving(
    source_urls,
    expected_source_urls,
    disable_langflow_ingest,
    task_method,
):
    """Keep file uploads available while disabling local archive storage."""
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "sample.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"%PDF-sample")

    mock_task_service = MagicMock()
    mock_task_service.create_langflow_upload_task = AsyncMock(return_value="task-1")
    mock_task_service.create_upload_task = AsyncMock(return_value="task-1")
    mock_temp_file = MagicMock()
    mock_temp_file.name = "/tmp/sample.pdf"
    user = User(user_id="user-1", email="u@example.com", name="User", jwt_token="Bearer tok")

    with (
        patch("api.router.get_openrag_config") as mock_cfg,
        patch("api.router.tempfile.NamedTemporaryFile", return_value=mock_temp_file),
        patch("api.router.open", create=True),
        patch("utils.file_utils.safe_unlink"),
        patch("api.router.is_ingest_preview_enabled", return_value=False),
        patch("config.settings.is_no_auth_mode", return_value=False),
        patch("api.documents._ensure_index_exists", new=AsyncMock()),
    ):
        mock_cfg.return_value.knowledge.disable_ingest_with_langflow = disable_langflow_ingest
        response = await upload_ingest_router(
            file=[mock_file],
            session_id=None,
            settings_json=None,
            tweaks_json=None,
            replace_duplicates="true",
            create_filter="false",
            preview="false",
            source_url=source_urls,
            archive_source=None,
            langflow_file_service=MagicMock(),
            session_manager=MagicMock(),
            task_service=mock_task_service,
            document_service=MagicMock(),
            user=user,
        )

    assert response.status_code == 202
    call_kwargs = getattr(mock_task_service, task_method).await_args.kwargs
    assert call_kwargs["source_urls"] == expected_source_urls
    assert call_kwargs["archive_sources"] is False


@pytest.mark.asyncio
async def test_multi_user_upload_rejects_local_archive_request():
    """Reject an explicit local archive request in multi-user mode."""
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "sample.pdf"
    mock_task_service = MagicMock()
    user = User(user_id="user-1", email="u@example.com", name="User", jwt_token="Bearer tok")

    with (
        patch("api.router.get_openrag_config") as mock_cfg,
        patch("config.settings.is_no_auth_mode", return_value=False),
    ):
        mock_cfg.return_value.knowledge.disable_ingest_with_langflow = False
        response = await upload_ingest_router(
            file=[mock_file],
            session_id=None,
            settings_json=None,
            tweaks_json=None,
            replace_duplicates="true",
            create_filter="false",
            preview="false",
            source_url=None,
            archive_source="true",
            langflow_file_service=MagicMock(),
            session_manager=MagicMock(),
            task_service=mock_task_service,
            document_service=MagicMock(),
            user=user,
        )

    assert response.status_code == 400
    mock_task_service.create_langflow_upload_task.assert_not_called()


def test_source_urls_must_be_http_and_match_uploaded_files():
    """Validate source URL count, protocol, credentials, and characters."""
    files = [MagicMock(spec=UploadFile), MagicMock(spec=UploadFile)]

    with pytest.raises(ValueError, match="once for each"):
        _normalize_source_urls(files, ["https://files.example.com/one.pdf"])

    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        _normalize_source_urls(files[:1], ["javascript:alert(1)"])

    with pytest.raises(ValueError, match="embedded credentials"):
        _normalize_source_urls(files[:1], ["https://user:secret@example.com/file.pdf"])

    with pytest.raises(ValueError, match="control characters"):
        _normalize_source_urls(files[:1], ["https://example.com/file\x7f.pdf"])


def test_manual_upload_uses_global_archiving_setting_when_form_field_is_absent(
    monkeypatch,
):
    """Use the global archive setting when an upload has no override."""
    monkeypatch.setattr(
        "services.local_source_service.is_source_archiving_enabled",
        lambda: True,
    )

    assert _resolve_archive_source(None) is True
    assert _resolve_archive_source("false") is False
