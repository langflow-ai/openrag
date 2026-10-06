"""Oversized uploads are refused at the edge, not in a background task.

Without the preflight, `upload_ingest_router` accepts the file, returns 202
with a task id, and the request dies minutes later when a proxy in front of
docling-serve rejects the multipart body with a 413 the user never sees.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from api.router import _oversized_upload_response, upload_ingest_router
from session_manager import User

MB = 1024 * 1024


def _upload(name: str, size: int | None) -> MagicMock:
    f = MagicMock(spec=UploadFile)
    f.filename = name
    f.content_type = "application/pdf"
    f.size = size
    f.read = AsyncMock(return_value=b"%PDF-sample")
    return f


def _user() -> User:
    return User(user_id="user-1", email="u@example.com", name="User", jwt_token="Bearer tok")


async def _call(files: list[MagicMock], task_service: MagicMock):
    temp_file = MagicMock()
    temp_file.name = "/tmp/sample.pdf"
    with (
        patch("api.router.tempfile.NamedTemporaryFile", return_value=temp_file),
        patch("api.router.open", create=True),
        patch("utils.file_utils.safe_unlink"),
    ):
        return await upload_ingest_router(
            file=files,
            document_service=MagicMock(),
            langflow_file_service=MagicMock(),
            session_manager=MagicMock(),
            task_service=task_service,
            user=_user(),
        )


@pytest.mark.asyncio
async def test_file_over_the_limit_is_refused_with_413():
    task_service = MagicMock()
    task_service.create_langflow_upload_task = AsyncMock(return_value="task-1")

    with (
        patch("config.settings.MAX_UPLOAD_SIZE_BYTES", 1 * MB),
        patch("config.settings.MAX_UPLOAD_SIZE_MB", 1),
    ):
        response = await _call([_upload("big.pdf", 2 * MB)], task_service)

    assert response.status_code == 413
    body = json.loads(response.body.decode())
    assert "big.pdf" in body["error"]
    assert "2.0 MB" in body["error"]
    assert body["max_upload_size_mb"] == 1
    # The decisive part: no task was created, so nothing fails later.
    task_service.create_langflow_upload_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_one_oversized_file_rejects_the_whole_batch():
    task_service = MagicMock()
    task_service.create_langflow_upload_task = AsyncMock(return_value="task-1")

    files = [_upload("ok.pdf", 10), _upload("big.pdf", 2 * MB)]
    with (
        patch("config.settings.MAX_UPLOAD_SIZE_BYTES", 1 * MB),
        patch("config.settings.MAX_UPLOAD_SIZE_MB", 1),
    ):
        response = await _call(files, task_service)

    assert response.status_code == 413
    body = json.loads(response.body.decode())
    assert "big.pdf" in body["error"]
    assert "ok.pdf" not in body["error"]
    task_service.create_langflow_upload_task.assert_not_awaited()


def test_file_at_the_limit_is_not_refused():
    with (
        patch("config.settings.MAX_UPLOAD_SIZE_BYTES", 1 * MB),
        patch("config.settings.MAX_UPLOAD_SIZE_MB", 1),
    ):
        assert _oversized_upload_response([_upload("exact.pdf", 1 * MB)]) is None


def test_unknown_size_is_not_refused():
    """Starlette leaves size unset when a part carries no length, and some
    callers pass an UploadFile-alike with no size attribute at all."""
    no_size = MagicMock(spec=UploadFile)
    no_size.filename = "no-attr.pdf"

    with (
        patch("config.settings.MAX_UPLOAD_SIZE_BYTES", 1 * MB),
        patch("config.settings.MAX_UPLOAD_SIZE_MB", 1),
    ):
        assert _oversized_upload_response([_upload("unknown.pdf", None)]) is None
        assert _oversized_upload_response([no_size]) is None
