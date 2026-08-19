import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.upload import UploadPathBody, upload_options, upload_path
from api.v1.documents import IngestPathV1Body, ingest_path_endpoint
from session_manager import User


@pytest.mark.asyncio
async def test_upload_path_archives_sources_without_temporary_cleanup(tmp_path, monkeypatch):
    """Archive path-ingested sources without treating them as temporary files."""
    monkeypatch.setattr("config.settings.is_no_auth_mode", lambda: True)
    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(tmp_path))
    monkeypatch.delenv("OPENRAG_INDEXED_DOCUMENTS_PATH", raising=False)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source = inbox / "message.eml"
    source.write_bytes(b"From: sender@example.com\n\nHello")

    task_service = MagicMock()
    task_service.create_upload_task = AsyncMock(return_value="task-1")
    ensure_index = AsyncMock()
    monkeypatch.setattr("api.documents._ensure_index_exists", ensure_index)
    user = User(
        user_id="user-1",
        email="user@example.com",
        name="User",
        jwt_token="Bearer token",
    )

    response = await upload_path(
        UploadPathBody(path=str(inbox), replace_duplicates=True, archive_sources=True),
        task_service=task_service,
        session_manager=MagicMock(),
        user=user,
    )

    assert response.status_code == 201
    assert json.loads(response.body)["archive_sources"] is True
    call = task_service.create_upload_task.await_args
    assert call.args[1] == [str(source.resolve())]
    kwargs = call.kwargs
    assert kwargs["replace_duplicates"] is True
    assert kwargs["archive_sources"] is True
    assert kwargs["cleanup_files"] is False
    assert kwargs["delete_source_after_success"] is True
    ensure_index.assert_awaited_once_with("Bearer token")


@pytest.mark.asyncio
async def test_v1_ingest_path_accepts_only_shared_documents(tmp_path, monkeypatch):
    """Confine public path ingestion to the shared documents directory."""
    monkeypatch.setattr("config.settings.is_no_auth_mode", lambda: True)
    documents = tmp_path / "documents"
    source = documents / "inbox" / "message.eml"
    source.parent.mkdir(parents=True)
    source.write_text("From: sender@example.com\n\nHello")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(documents))

    task_service = MagicMock()
    task_service.create_upload_task = AsyncMock(return_value="task-2")
    ensure_index = AsyncMock()
    monkeypatch.setattr("api.documents._ensure_index_exists", ensure_index)
    user = User(
        user_id="user-1",
        email="user@example.com",
        name="User",
        jwt_token="Bearer token",
    )

    accepted = await ingest_path_endpoint(
        IngestPathV1Body(
            path="inbox/message.eml",
            replace_duplicates=True,
            archive_source=True,
        ),
        task_service=task_service,
        session_manager=MagicMock(),
        user=user,
    )
    rejected = await ingest_path_endpoint(
        IngestPathV1Body(path=str(outside)),
        task_service=task_service,
        session_manager=MagicMock(),
        user=user,
    )

    assert accepted.status_code == 201
    assert rejected.status_code == 400
    assert task_service.create_upload_task.await_count == 1


@pytest.mark.asyncio
async def test_internal_upload_path_is_also_confined_to_shared_documents(tmp_path, monkeypatch):
    """Confine internal path ingestion to the shared documents directory."""
    monkeypatch.setattr("config.settings.is_no_auth_mode", lambda: True)
    documents = tmp_path / "documents"
    documents.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(documents))
    task_service = MagicMock()
    task_service.create_upload_task = AsyncMock(return_value="task")
    user = User(
        user_id="user-1",
        email="user@example.com",
        name="User",
        jwt_token="Bearer token",
    )

    response = await upload_path(
        UploadPathBody(path=str(outside)),
        task_service=task_service,
        session_manager=MagicMock(),
        user=user,
    )

    assert response.status_code == 400
    task_service.create_upload_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_path_ingestion_is_disabled_in_multi_user_mode(tmp_path, monkeypatch):
    """Disable every local path ingestion surface in multi-user mode."""
    documents = tmp_path / "documents"
    source = documents / "message.eml"
    documents.mkdir()
    source.write_text("message")
    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(documents))
    monkeypatch.setattr("config.settings.is_no_auth_mode", lambda: False)
    task_service = MagicMock()
    task_service.create_upload_task = AsyncMock(return_value="task")
    user = User(
        user_id="user-1",
        email="user@example.com",
        name="User",
        jwt_token="Bearer token",
    )

    internal = await upload_path(
        UploadPathBody(path=str(source)),
        task_service=task_service,
        session_manager=MagicMock(),
        user=user,
    )
    public = await ingest_path_endpoint(
        IngestPathV1Body(path=str(source)),
        task_service=task_service,
        session_manager=MagicMock(),
        user=user,
    )
    options = await upload_options(user=user)

    assert internal.status_code == 403
    assert public.status_code == 403
    options_payload = json.loads(options.body)
    assert options_payload["local_path_ingestion_enabled"] is False
    assert "documents_path" not in options_payload
    task_service.create_upload_task.assert_not_awaited()
