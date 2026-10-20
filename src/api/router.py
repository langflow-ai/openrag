"""Router endpoints that automatically route based on configuration settings."""

import json
import mimetypes
import os
import tempfile

from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from config.settings import get_openrag_config
from dependencies import (
    get_current_user,
    get_document_service,
    get_langflow_file_service,
    get_rbac_service,
    get_session_manager,
    get_task_service,
    has_effective_permission,
)
from session_manager import User
from utils.ingest_preview_flag import is_ingest_preview_enabled
from utils.logging_config import get_logger
from utils.upload_limits import UploadTooLarge, read_upload_within_limit

logger = get_logger(__name__)


def _form_str(value) -> str | None:
    """A real form string. A direct call leaves FastAPI's Form default in place."""
    return value if isinstance(value, str) else None


def _rejected_uploads(raw: str | None) -> list[tuple[str, int]]:
    """Files the client kept out of the body because they exceed the limit."""
    if not isinstance(raw, str) or not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    rejections: list[tuple[str, int]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("filename")
        size = item.get("size")
        if isinstance(name, str) and name and isinstance(size, int) and size >= 0:
            rejections.append((name, size))
    return rejections


def _rejection_only_response(task_service, user_id: str, rejections: list[tuple[str, int]]):
    if not rejections:
        return None
    task_id = task_service.record_rejected_uploads(user_id, rejections)
    return JSONResponse(
        {
            "task_id": task_id,
            "message": f"{len(rejections)} file(s) were over the upload limit",
            "file_count": 0,
            "preview_mode": False,
        },
        status_code=202,
    )


async def upload_ingest_router(
    request: Request,
    file: list[UploadFile] | None = File(None),
    session_id: str | None = Form(None),
    existing_task_id: str | None = Form(None),
    rejected_files: str | None = Form(None),
    settings_json: str | None = Form(None, alias="settings"),
    tweaks_json: str | None = Form(None, alias="tweaks"),
    replace_duplicates: str = Form("true"),
    create_filter: str = Form("false"),
    preview: str = Form("false"),
    document_service=Depends(get_document_service),
    langflow_file_service=Depends(get_langflow_file_service),
    session_manager=Depends(get_session_manager),
    task_service=Depends(get_task_service),
    user: User = Depends(get_current_user),
    rbac=Depends(get_rbac_service),
):
    """
    Router endpoint that automatically routes upload requests based on configuration.

    - If DISABLE_INGEST_WITH_LANGFLOW is True: uses traditional OpenRAG upload
    - If DISABLE_INGEST_WITH_LANGFLOW is False (default): uses Langflow upload-ingest via task service
    """
    disable_ingest_with_langflow = get_openrag_config().knowledge.disable_ingest_with_langflow
    requested_preview = preview.lower() == "true"
    preview_mode = requested_preview and is_ingest_preview_enabled()
    if requested_preview and not preview_mode:
        logger.debug("Ingest preview ignored — not available in this run mode")
    logger.debug(
        "Router upload_ingest endpoint called",
        disable_langflow_ingest=disable_ingest_with_langflow,
        preview_mode=preview_mode,
    )

    # Resolved here, where the request and the RBAC service are, and carried
    # down to the processor. Overwriting a file whose name belongs to a shared
    # (ownerless) document deletes that document for the whole instance, so it
    # takes the same permission the explicit delete endpoints ask for.
    allow_anonymous_delete = await has_effective_permission(
        request, user, rbac, "knowledge:delete:anonymous"
    )
    upload_files = file or []
    existing_task_id = _form_str(existing_task_id)
    rejections = _rejected_uploads(rejected_files)

    if disable_ingest_with_langflow:
        logger.debug("Routing to traditional OpenRAG upload via task service")
        return await _traditional_upload_ingest_task(
            upload_files=upload_files,
            replace_duplicates=replace_duplicates.lower() == "true",
            create_filter=create_filter.lower() == "true",
            preview_mode=preview_mode,
            session_manager=session_manager,
            task_service=task_service,
            user=user,
            allow_anonymous_delete=allow_anonymous_delete,
            settings_json=settings_json,
            existing_task_id=existing_task_id,
            rejected_uploads=rejections,
        )

    logger.debug("Routing to Langflow upload-ingest pipeline via task service")
    return await _langflow_upload_ingest_task(
        upload_files=upload_files,
        session_id=session_id,
        settings_json=settings_json,
        tweaks_json=tweaks_json,
        replace_duplicates=replace_duplicates.lower() == "true",
        create_filter=create_filter.lower() == "true",
        preview_mode=preview_mode,
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        task_service=task_service,
        user=user,
        allow_anonymous_delete=allow_anonymous_delete,
        existing_task_id=existing_task_id,
        rejected_uploads=rejections,
    )


async def _traditional_upload_ingest_task(
    upload_files: list[UploadFile],
    replace_duplicates: bool,
    create_filter: bool,
    preview_mode: bool,
    session_manager,
    task_service,
    user: User,
    allow_anonymous_delete: bool,
    settings_json: str | None = None,
    existing_task_id: str | None = None,
    rejected_uploads: list[tuple[str, int]] | None = None,
):
    """Task-based traditional upload and ingest for single/multiple files"""
    rejections = rejected_uploads or []
    try:
        if not upload_files:
            only_rejections = _rejection_only_response(task_service, user.user_id, rejections)
            if only_rejections is not None:
                return only_rejections
            return JSONResponse({"error": "Missing files"}, status_code=400)

        settings = None
        if settings_json:
            try:
                settings = json.loads(settings_json)
            except json.JSONDecodeError as e:
                return JSONResponse({"error": f"Invalid settings JSON: {e}"}, status_code=400)

        user_id = user.user_id
        user_name = user.name
        user_email = user.email
        jwt_token = user.jwt_token

        temp_file_paths = []
        original_filenames = []

        try:
            for upload_file in upload_files:
                content = await read_upload_within_limit(upload_file)
                original_filenames.append(upload_file.filename)
                # Generate unique temp file with the original extension to assist docling/format detection
                suffix = os.path.splitext(upload_file.filename)[1] if upload_file.filename else ""
                if not suffix and upload_file.content_type:
                    from utils.file_utils import get_file_extension

                    suffix = get_file_extension(upload_file.content_type)
                    if not suffix:
                        suffix = mimetypes.guess_extension(upload_file.content_type)
                if not suffix:
                    suffix = ".tmp"
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                temp_path = temp_file.name
                temp_file.close()
                with open(temp_path, "wb") as f:
                    f.write(content)
                temp_file_paths.append(temp_path)

            file_path_to_original_filename = dict(
                zip(temp_file_paths, original_filenames, strict=True)
            )

            # Ensure the search index exists before creating the upload task
            from api.documents import _ensure_index_exists

            await _ensure_index_exists(jwt_token)

            task_id = await task_service.create_upload_task(
                user_id=user_id,
                file_paths=temp_file_paths,
                jwt_token=jwt_token,
                owner_name=user_name,
                owner_email=user_email,
                original_filenames=file_path_to_original_filename,
                replace_duplicates=replace_duplicates,
                settings=settings,
                preview_mode=preview_mode,
                allow_anonymous_delete=allow_anonymous_delete,
                existing_task_id=existing_task_id,
            )
            if rejections and not existing_task_id:
                task_service.record_rejected_uploads(user_id, rejections, task_id=task_id)

            return JSONResponse(
                {
                    "task_id": task_id,
                    "message": f"Upload task created for {len(upload_files)} file(s)",
                    "file_count": len(upload_files),
                    "create_filter": create_filter,
                    "filename": original_filenames[0] if len(original_filenames) == 1 else None,
                    "preview_mode": preview_mode,
                },
                status_code=202,
            )

        except Exception:
            from utils.file_utils import safe_unlink

            for temp_path in temp_file_paths:
                safe_unlink(temp_path)
            raise

    except UploadTooLarge as e:
        return JSONResponse({"error": str(e)}, status_code=413)
    except Exception as e:
        logger.error("Task-based traditional upload_ingest failed", error=str(e))
        import traceback

        logger.error("Full traceback", traceback=traceback.format_exc())
        error_msg = str(e)
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse({"error": "Access denied"}, status_code=403)
        return JSONResponse({"error": "An internal error has occurred."}, status_code=500)


async def _langflow_upload_ingest_task(
    upload_files: list[UploadFile],
    session_id,
    settings_json,
    tweaks_json,
    replace_duplicates: bool,
    create_filter: bool,
    preview_mode: bool,
    langflow_file_service,
    session_manager,
    task_service,
    user: User,
    allow_anonymous_delete: bool,
    existing_task_id: str | None = None,
    rejected_uploads: list[tuple[str, int]] | None = None,
):
    """Task-based langflow upload and ingest for single/multiple files"""
    rejections = rejected_uploads or []
    try:
        if not upload_files:
            only_rejections = _rejection_only_response(task_service, user.user_id, rejections)
            if only_rejections is not None:
                return only_rejections
            return JSONResponse({"error": "Missing files"}, status_code=400)

        settings = None
        tweaks = None

        if settings_json:
            try:
                settings = json.loads(settings_json)
            except json.JSONDecodeError as e:
                return JSONResponse({"error": f"Invalid settings JSON: {e}"}, status_code=400)

        if tweaks_json:
            try:
                tweaks = json.loads(tweaks_json)
            except json.JSONDecodeError as e:
                return JSONResponse({"error": f"Invalid tweaks JSON: {e}"}, status_code=400)

        user_id = user.user_id
        user_name = user.name
        user_email = user.email
        jwt_token = user.jwt_token

        temp_file_paths = []
        original_filenames = []

        try:
            for upload_file in upload_files:
                content = await read_upload_within_limit(upload_file)
                original_filenames.append(upload_file.filename)
                # Generate unique temp file with the original extension to assist docling/format detection
                suffix = os.path.splitext(upload_file.filename)[1] if upload_file.filename else ""
                if not suffix and upload_file.content_type:
                    from utils.file_utils import get_file_extension

                    suffix = get_file_extension(upload_file.content_type)
                    if not suffix:
                        suffix = mimetypes.guess_extension(upload_file.content_type)
                if not suffix:
                    suffix = ".tmp"
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                temp_path = temp_file.name
                temp_file.close()
                with open(temp_path, "wb") as f:
                    f.write(content)
                temp_file_paths.append(temp_path)

            file_path_to_original_filename = dict(
                zip(temp_file_paths, original_filenames, strict=True)
            )

            task_id = await task_service.create_langflow_upload_task(
                user_id=user_id,
                file_paths=temp_file_paths,
                original_filenames=file_path_to_original_filename,
                langflow_file_service=langflow_file_service,
                session_manager=session_manager,
                jwt_token=jwt_token,
                owner_name=user_name,
                owner_email=user_email,
                session_id=session_id,
                tweaks=tweaks,
                settings=settings,
                replace_duplicates=replace_duplicates,
                preview_mode=preview_mode,
                allow_anonymous_delete=allow_anonymous_delete,
                existing_task_id=existing_task_id,
            )
            if rejections and not existing_task_id:
                task_service.record_rejected_uploads(user_id, rejections, task_id=task_id)

            return JSONResponse(
                {
                    "task_id": task_id,
                    "message": f"Langflow upload task created for {len(upload_files)} file(s)",
                    "file_count": len(upload_files),
                    "create_filter": create_filter,
                    "filename": original_filenames[0] if len(original_filenames) == 1 else None,
                    "preview_mode": preview_mode,
                },
                status_code=202,
            )

        except Exception:
            from utils.file_utils import safe_unlink

            for temp_path in temp_file_paths:
                safe_unlink(temp_path)
            raise

    except UploadTooLarge as e:
        return JSONResponse({"error": str(e)}, status_code=413)
    except Exception as e:
        logger.error("Task-based langflow upload_ingest failed", error=str(e))
        import traceback

        logger.error("Full traceback", traceback=traceback.format_exc())
        error_msg = str(e)
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=403)
        return JSONResponse({"error": error_msg}, status_code=500)
