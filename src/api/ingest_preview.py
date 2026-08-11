"""Ephemeral ingest preview endpoints for preview-mode ingest."""

from typing import Annotated, Any

from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from dependencies import (
    get_chunk_draft_service,
    get_ingest_preview_service,
    get_models_service,
    get_session_manager,
    get_task_service,
    require_permission,
)
from session_manager import User
from utils.ingest_preview_flag import is_ingest_preview_enabled
from utils.logging_config import get_logger

logger = get_logger(__name__)


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


def _resolve_file_task(upload_task: Any, file_path: str | None):
    if file_path is not None:
        file_task = upload_task.file_tasks.get(file_path)
        if file_task is None:
            return None, JSONResponse({"error": "File not found in preview task"}, status_code=404)
        return file_task, None
    file_task = next(iter(upload_task.file_tasks.values()), None)
    if file_task is None:
        return None, JSONResponse({"error": "File not found in preview task"}, status_code=404)
    return file_task, None


class PatchDraftChunkBody(BaseModel):
    text: str = Field(min_length=1)


async def get_parse_preview(
    task_id: str,
    preview_service: Annotated[Any, Depends(get_ingest_preview_service)],
    task_service: Annotated[Any, Depends(get_task_service)],
    user: Annotated[User, Depends(require_permission("knowledge:upload"))],
    file: str | None = None,
):
    """Return cached Docling JSON for a preview-mode ingest task.

    ``file`` selects a specific file within a multi-file preview task (the
    file_path key from the task status). Omitted = first available file.
    """
    _, error = _require_preview_task(task_service, user, task_id)
    if error is not None:
        return error

    preview = preview_service.get_docling_preview(user.user_id, task_id, file_path=file)
    if preview is None:
        return JSONResponse({"error": "Parse preview not available yet"}, status_code=404)

    return JSONResponse(
        {
            "task_id": task_id,
            "document": preview["document"],
            "stats": preview["stats"],
            "expires_at": preview["expires_at"],
            "document_id": preview.get("document_id"),
            "file_path": preview.get("file_path"),
            "filename": preview.get("filename"),
        }
    )


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


async def get_chunk_draft(
    task_id: str,
    draft_service: Annotated[Any, Depends(get_chunk_draft_service)],
    task_service: Annotated[Any, Depends(get_task_service)],
    session_manager: Annotated[Any, Depends(get_session_manager)],
    user: Annotated[User, Depends(require_permission("knowledge:upload"))],
    file: str | None = None,
):
    """Return last-changes draft (seeds from OpenSearch on first call)."""
    upload_task, error = _require_preview_task(task_service, user, task_id)
    if error is not None:
        return error

    file_task, file_error = _resolve_file_task(upload_task, file)
    if file_error is not None:
        return file_error

    document_id = getattr(file_task, "document_id", None)
    if not document_id:
        return JSONResponse({"error": "Document not indexed yet"}, status_code=404)

    opensearch_client = session_manager.get_user_opensearch_client(user.user_id, user.jwt_token)
    try:
        session = await draft_service.ensure_seeded(
            user_id=user.user_id,
            task_id=task_id,
            file_path=file if file is not None else getattr(file_task, "file_path", None),
            document_id=document_id,
            opensearch_client=opensearch_client,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        logger.warning("Failed to seed chunk draft", task_id=task_id, error=str(exc))
        return JSONResponse({"error": "Failed to load chunk draft"}, status_code=500)

    return JSONResponse({"task_id": task_id, **draft_service.session_public(session)})


async def patch_chunk_draft(
    task_id: str,
    chunk_id: str,
    body: PatchDraftChunkBody,
    draft_service: Annotated[Any, Depends(get_chunk_draft_service)],
    task_service: Annotated[Any, Depends(get_task_service)],
    session_manager: Annotated[Any, Depends(get_session_manager)],
    user: Annotated[User, Depends(require_permission("knowledge:upload"))],
    file: str | None = None,
):
    """Update chunk text in last-changes only (no OpenSearch write)."""
    upload_task, error = _require_preview_task(task_service, user, task_id)
    if error is not None:
        return error

    file_task, file_error = _resolve_file_task(upload_task, file)
    if file_error is not None:
        return file_error

    document_id = getattr(file_task, "document_id", None)
    if not document_id:
        return JSONResponse({"error": "Document not indexed yet"}, status_code=404)

    file_path = file if file is not None else getattr(file_task, "file_path", None)
    opensearch_client = session_manager.get_user_opensearch_client(user.user_id, user.jwt_token)
    try:
        session = await draft_service.ensure_seeded(
            user_id=user.user_id,
            task_id=task_id,
            file_path=file_path,
            document_id=document_id,
            opensearch_client=opensearch_client,
        )
        chunk = draft_service.update_chunk_text(session, chunk_id, body.text)
    except KeyError:
        return JSONResponse({"error": "Chunk not found in draft"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.warning("Failed to patch chunk draft", task_id=task_id, error=str(exc))
        return JSONResponse({"error": "Failed to update chunk draft"}, status_code=500)

    return JSONResponse(
        {
            "task_id": task_id,
            "chunk": chunk.to_public(),
            **draft_service.session_public(session),
        }
    )


async def delete_chunk_draft(
    task_id: str,
    chunk_id: str,
    draft_service: Annotated[Any, Depends(get_chunk_draft_service)],
    task_service: Annotated[Any, Depends(get_task_service)],
    session_manager: Annotated[Any, Depends(get_session_manager)],
    user: Annotated[User, Depends(require_permission("knowledge:upload"))],
    file: str | None = None,
):
    """Remove a chunk from last-changes only."""
    upload_task, error = _require_preview_task(task_service, user, task_id)
    if error is not None:
        return error

    file_task, file_error = _resolve_file_task(upload_task, file)
    if file_error is not None:
        return file_error

    document_id = getattr(file_task, "document_id", None)
    if not document_id:
        return JSONResponse({"error": "Document not indexed yet"}, status_code=404)

    file_path = file if file is not None else getattr(file_task, "file_path", None)
    opensearch_client = session_manager.get_user_opensearch_client(user.user_id, user.jwt_token)
    try:
        session = await draft_service.ensure_seeded(
            user_id=user.user_id,
            task_id=task_id,
            file_path=file_path,
            document_id=document_id,
            opensearch_client=opensearch_client,
        )
        draft_service.delete_chunk(session, chunk_id)
    except KeyError:
        return JSONResponse({"error": "Chunk not found in draft"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.warning("Failed to delete chunk draft", task_id=task_id, error=str(exc))
        return JSONResponse({"error": "Failed to delete chunk draft"}, status_code=500)

    return JSONResponse({"task_id": task_id, **draft_service.session_public(session)})


async def revert_chunk_draft(
    task_id: str,
    draft_service: Annotated[Any, Depends(get_chunk_draft_service)],
    task_service: Annotated[Any, Depends(get_task_service)],
    session_manager: Annotated[Any, Depends(get_session_manager)],
    user: Annotated[User, Depends(require_permission("knowledge:upload"))],
    file: str | None = None,
):
    """Reset last-changes to Docling original."""
    upload_task, error = _require_preview_task(task_service, user, task_id)
    if error is not None:
        return error

    file_task, file_error = _resolve_file_task(upload_task, file)
    if file_error is not None:
        return file_error

    document_id = getattr(file_task, "document_id", None)
    if not document_id:
        return JSONResponse({"error": "Document not indexed yet"}, status_code=404)

    file_path = file if file is not None else getattr(file_task, "file_path", None)
    opensearch_client = session_manager.get_user_opensearch_client(user.user_id, user.jwt_token)
    try:
        session = await draft_service.ensure_seeded(
            user_id=user.user_id,
            task_id=task_id,
            file_path=file_path,
            document_id=document_id,
            opensearch_client=opensearch_client,
        )
        draft_service.revert(session)
    except Exception as exc:
        logger.warning("Failed to revert chunk draft", task_id=task_id, error=str(exc))
        return JSONResponse({"error": "Failed to revert chunk draft"}, status_code=500)

    return JSONResponse({"task_id": task_id, **draft_service.session_public(session)})


async def commit_chunk_draft(
    task_id: str,
    draft_service: Annotated[Any, Depends(get_chunk_draft_service)],
    task_service: Annotated[Any, Depends(get_task_service)],
    session_manager: Annotated[Any, Depends(get_session_manager)],
    models_service: Annotated[Any, Depends(get_models_service)],
    user: Annotated[User, Depends(require_permission("knowledge:upload"))],
    file: str | None = None,
):
    """Commit last-changes to OpenSearch (re-embed dirty chunks)."""
    from config.settings import clients

    upload_task, error = _require_preview_task(task_service, user, task_id)
    if error is not None:
        return error

    file_task, file_error = _resolve_file_task(upload_task, file)
    if file_error is not None:
        return file_error

    document_id = getattr(file_task, "document_id", None)
    if not document_id:
        return JSONResponse({"error": "Document not indexed yet"}, status_code=404)

    file_path = file if file is not None else getattr(file_task, "file_path", None)
    opensearch_client = session_manager.get_user_opensearch_client(user.user_id, user.jwt_token)
    write_client = clients.opensearch

    async def embed_texts(embedding_model: str, texts: list[str]) -> list[list[float]]:
        litellm_model = await models_service.get_litellm_model_name(embedding_model)
        model_name = litellm_model or embedding_model
        resp = await clients.patched_embedding_client.embeddings.create(
            model=model_name, input=texts
        )
        return [d["embedding"] if isinstance(d, dict) else d.embedding for d in resp.data]

    try:
        session = await draft_service.ensure_seeded(
            user_id=user.user_id,
            task_id=task_id,
            file_path=file_path,
            document_id=document_id,
            opensearch_client=opensearch_client,
        )
        result = await draft_service.commit(
            session,
            opensearch_client=opensearch_client,
            write_client=write_client,
            embed_texts=embed_texts,
        )
    except Exception as exc:
        logger.warning("Failed to commit chunk draft", task_id=task_id, error=str(exc))
        return JSONResponse({"error": f"Failed to commit chunk draft: {exc}"}, status_code=500)

    return JSONResponse({"task_id": task_id, **result})
