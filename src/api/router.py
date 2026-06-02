"""Router endpoints that automatically route based on configuration settings."""

import json
import tempfile

from fastapi import Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from config.settings import get_openrag_config
from dependencies import (
    get_current_user,
    get_document_service,
    get_langflow_file_service,
    get_session_manager,
    get_task_service,
)
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def upload_ingest_router(
    file: list[UploadFile] = File(...),
    session_id: str | None = Form(None),
    settings_json: str | None = Form(None, alias="settings"),
    tweaks_json: str | None = Form(None, alias="tweaks"),
    replace_duplicates: str = Form("true"),
    create_filter: str = Form("false"),
    document_service=Depends(get_document_service),
    langflow_file_service=Depends(get_langflow_file_service),
    session_manager=Depends(get_session_manager),
    task_service=Depends(get_task_service),
    user: User = Depends(get_current_user),
):
    """
    Router endpoint that automatically routes upload requests based on configuration.

    - If DISABLE_INGEST_WITH_LANGFLOW is True: uses traditional OpenRAG upload
    - If DISABLE_INGEST_WITH_LANGFLOW is False (default): uses Langflow upload-ingest via task service
    """
    disable_ingest_with_langflow = get_openrag_config().knowledge.disable_ingest_with_langflow
    logger.debug(
        "Router upload_ingest endpoint called",
        disable_langflow_ingest=disable_ingest_with_langflow,
    )

    if disable_ingest_with_langflow:
        logger.debug("Routing to traditional OpenRAG upload via task service")
        return await _traditional_upload_ingest_task(
            upload_files=file,
            replace_duplicates=replace_duplicates.lower() == "true",
            create_filter=create_filter.lower() == "true",
            session_manager=session_manager,
            task_service=task_service,
            user=user,
            settings_json=settings_json,
        )

    logger.debug("Routing to Langflow upload-ingest pipeline via task service")
    return await _langflow_upload_ingest_task(
        upload_files=file,
        session_id=session_id,
        settings_json=settings_json,
        tweaks_json=tweaks_json,
        replace_duplicates=replace_duplicates.lower() == "true",
        create_filter=create_filter.lower() == "true",
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        task_service=task_service,
        user=user,
    )


async def _traditional_upload_ingest_task(
    upload_files: list[UploadFile],
    replace_duplicates: bool,
    create_filter: bool,
    session_manager,
    task_service,
    user: User,
    settings_json: str | None = None,
):
    """Task-based traditional upload and ingest for single/multiple files"""
    try:
        if not upload_files:
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
                content = await upload_file.read()
                original_filenames.append(upload_file.filename)
                # Generate unique temp file to avoid collisions
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".tmp")
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
            )

            return JSONResponse(
                {
                    "task_id": task_id,
                    "message": f"Upload task created for {len(upload_files)} file(s)",
                    "file_count": len(upload_files),
                    "create_filter": create_filter,
                    "filename": original_filenames[0] if len(original_filenames) == 1 else None,
                },
                status_code=202,
            )

        except Exception:
            from utils.file_utils import safe_unlink

            for temp_path in temp_file_paths:
                safe_unlink(temp_path)
            raise

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
    langflow_file_service,
    session_manager,
    task_service,
    user: User,
):
    """Task-based langflow upload and ingest for single/multiple files"""
    try:
        if not upload_files:
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
                content = await upload_file.read()
                original_filenames.append(upload_file.filename)
                # Generate unique temp file to avoid collisions
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".tmp")
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
            )

            return JSONResponse(
                {
                    "task_id": task_id,
                    "message": f"Langflow upload task created for {len(upload_files)} file(s)",
                    "file_count": len(upload_files),
                    "create_filter": create_filter,
                    "filename": original_filenames[0] if len(original_filenames) == 1 else None,
                },
                status_code=202,
            )

        except Exception:
            from utils.file_utils import safe_unlink

            for temp_path in temp_file_paths:
                safe_unlink(temp_path)
            raise

    except Exception as e:
        logger.error("Task-based langflow upload_ingest failed", error=str(e))
        import traceback

        logger.error("Full traceback", traceback=traceback.format_exc())
        error_msg = str(e)
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=403)
        return JSONResponse({"error": error_msg}, status_code=500)
