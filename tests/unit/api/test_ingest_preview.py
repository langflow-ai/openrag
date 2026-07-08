"""API tests for ingest preview endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import JSONResponse

from api.ingest_preview import get_index_proof
from session_manager import User


@pytest.fixture(autouse=True)
def enable_ingest_preview():
    with patch("api.ingest_preview.is_ingest_preview_enabled", return_value=True):
        yield


@pytest.fixture
def user():
    return User(user_id="user-1", email="u@example.com", name="User", jwt_token="Bearer tok")


@pytest.fixture
def preview_service():
    service = MagicMock()
    service.get_index_proof = AsyncMock(
        return_value={
            "ready": True,
            "phase": "complete",
            "chunk_count": 2,
            "embedding_model": "text-embedding-3-small",
            "embedding_dimensions": 1536,
            "chunks": [
                {"chunk_id": "hash-1_0", "page": 1, "text_preview": "Hello", "char_count": 5}
            ],
        }
    )
    return service


@pytest.fixture
def task_service():
    upload_task = MagicMock()
    upload_task.preview_mode = True
    service = MagicMock()
    service.get_upload_task.return_value = upload_task
    return service


@pytest.mark.asyncio
async def test_get_index_proof_uses_validated_upload_task_without_refetch(
    user, preview_service, task_service
):
    """Regression: index proof must use the task validated by _require_preview_task."""
    upload_task = task_service.get_upload_task.return_value
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client.return_value = AsyncMock()

    await get_index_proof(
        task_id="task-1",
        preview_service=preview_service,
        task_service=task_service,
        session_manager=session_manager,
        user=user,
    )

    task_service.get_upload_task.assert_called_once_with("user-1", "task-1")
    call_kwargs = preview_service.get_index_proof.await_args.kwargs
    assert call_kwargs["upload_task"] is upload_task
    assert "task_service" not in call_kwargs
    assert "user_id" not in call_kwargs


@pytest.mark.asyncio
async def test_get_index_proof_returns_chunk_metadata(user, preview_service, task_service):
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client.return_value = AsyncMock()

    response = await get_index_proof(
        task_id="task-1",
        preview_service=preview_service,
        task_service=task_service,
        session_manager=session_manager,
        user=user,
    )

    assert response.status_code == 200
    preview_service.get_index_proof.assert_awaited_once()
    call_kwargs = preview_service.get_index_proof.await_args.kwargs
    assert call_kwargs["upload_task"] is task_service.get_upload_task.return_value
    assert call_kwargs["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_get_index_proof_task_not_found(user, preview_service):
    task_service = MagicMock()
    task_service.get_upload_task.return_value = None

    response = await get_index_proof(
        task_id="missing",
        preview_service=preview_service,
        task_service=task_service,
        session_manager=MagicMock(),
        user=user,
    )

    assert response.status_code == 404
    preview_service.get_index_proof.assert_not_called()


@pytest.mark.asyncio
async def test_get_index_proof_returns_file_not_found(user, preview_service, task_service):
    preview_service.get_index_proof = AsyncMock(
        return_value={
            "ready": False,
            "error": "file_not_found",
            "phase": "docling",
            "chunk_count": 0,
            "chunks": [],
            "chunks_returned": 0,
            "chunks_truncated": False,
            "document_id": None,
        }
    )

    response = await get_index_proof(
        task_id="task-1",
        preview_service=preview_service,
        task_service=task_service,
        session_manager=MagicMock(),
        user=user,
        file="/tmp/missing.pdf",
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_index_proof_unavailable_when_disabled(user, preview_service, task_service):
    with patch("api.ingest_preview.is_ingest_preview_enabled", return_value=False):
        response = await get_index_proof(
            task_id="task-1",
            preview_service=preview_service,
            task_service=task_service,
            session_manager=MagicMock(),
            user=user,
        )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 404
    preview_service.get_index_proof.assert_not_called()
