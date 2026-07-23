"""Ephemeral ingest preview endpoints for preview-mode ingest."""

from typing import Annotated, Any

from fastapi import Depends
from fastapi.responses import JSONResponse

from dependencies import (
    get_ingest_preview_service,
    get_session_manager,
    get_task_service,
    require_permission,
)
from session_manager import User
from utils.ingest_preview_flag import is_ingest_preview_enabled


def _preview_unavailable_response() -> JSONResponse:
    return JSONResponse(
        {"error": "Ingest preview is not available in this run mode"},
        status_code=404,
    )


def _require_preview_task(task_service: Any, user: User, task_id: str):
    """Return (upload_task, error_response). Exactly one of the tuple values is None."""
    if not is_ingest_preview_enabled():
        return None, _preview_unavailable_response()

    upload_task = task_service.get_upload_task(user.user_id, task_id)
    if upload_task is None:
        return None, JSONResponse({"error": "Task not found"}, status_code=404)
    if not upload_task.preview_mode:
        return None, JSONResponse({"error": "Task is not a preview ingest"}, status_code=404)
    return upload_task, None


async def get_index_proof(
    task_id: str,
    preview_service: Annotated[Any, Depends(get_ingest_preview_service)],
    task_service: Annotated[Any, Depends(get_task_service)],
    session_manager: Annotated[Any, Depends(get_session_manager)],
    user: Annotated[User, Depends(require_permission("knowledge:upload"))],
    file: str | None = None,
):
    """Return indexed chunk metadata proving embeddings landed in OpenSearch.

    ``file`` selects a specific file within a multi-file preview task.
    """
    upload_task, error = _require_preview_task(task_service, user, task_id)
    if error is not None:
        return error

    opensearch_client = session_manager.get_user_opensearch_client(user.user_id, user.jwt_token)
    proof = await preview_service.get_index_proof(
        upload_task=upload_task,
        task_id=task_id,
        opensearch_client=opensearch_client,
        file_path=file,
    )

    if proof.get("error") == "not_preview_task":
        return JSONResponse({"error": "Task is not a preview ingest"}, status_code=404)
    if proof.get("error") == "file_not_found":
        return JSONResponse({"error": "File not found in preview task"}, status_code=404)

    return JSONResponse({"task_id": task_id, **proof})
