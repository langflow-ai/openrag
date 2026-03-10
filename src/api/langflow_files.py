import json
import os
import tempfile
from typing import List, Optional

from fastapi import Depends, File, Form, UploadFile
from pydantic import BaseModel
from fastapi.responses import JSONResponse

from dependencies import (
    get_langflow_file_service,
    get_session_manager,
    get_task_service,
    get_current_user,
    get_optional_user,
)
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


class RunIngestionBody(BaseModel):
    file_paths: List[str] = []
    file_ids: Optional[List[str]] = None
    file_metadata: Optional[List[dict]] = None
    session_id: Optional[str] = None
    tweaks: Optional[dict] = None
    settings: Optional[dict] = None


class DeleteFilesBody(BaseModel):
    file_ids: List[str]


async def upload_user_file(
    file: UploadFile = File(...),
    langflow_file_service=Depends(get_langflow_file_service),
    session_manager=Depends(get_session_manager),
    user: Optional[User] = Depends(get_optional_user),
):
    """Upload a file to Langflow's Files API"""
    try:
        logger.debug("upload_user_file endpoint called")
        logger.debug("Processing file", filename=file.filename, size=file.size)

        content = await file.read()
        file_tuple = (
            file.filename,
            content,
            file.content_type or "application/octet-stream",
        )

        jwt_token = user.jwt_token if user else session_manager.get_effective_jwt_token(None, None)

        logger.debug("Calling langflow_file_service.upload_user_file")
        result = await langflow_file_service.upload_user_file(file_tuple, jwt_token)
        logger.debug("Upload successful", result=result)
        return JSONResponse(result, status_code=201)
    except Exception as e:
        logger.error("upload_user_file endpoint failed", error_type=type(e).__name__, error=str(e))
        import traceback
        logger.error("Full traceback", traceback=traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)


async def run_ingestion(
    body: RunIngestionBody,
    langflow_file_service=Depends(get_langflow_file_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Run a Langflow ingestion flow"""
    if not body.file_paths and not body.file_ids:
        return JSONResponse({"error": "Provide file_paths or file_ids"}, status_code=400)

    # Build file_tuples from file_metadata if provided
    file_tuples = []
    file_metadata = body.file_metadata or []
    for i, file_path in enumerate(body.file_paths):
        if i < len(file_metadata):
            meta = file_metadata[i]
            filename = meta.get("filename", "")
            mimetype = meta.get("mimetype", "application/octet-stream")
            file_tuples.append((filename, b"", mimetype))
        else:
            filename = os.path.basename(file_path)
            file_tuples.append((filename, b"", "application/octet-stream"))

    tweaks = body.tweaks or {}
    settings = body.settings or {}

    # Convert UI settings to component tweaks
    if settings:
        logger.debug("Applying ingestion settings", settings=settings)
        if settings.get("chunkSize") or settings.get("chunkOverlap") or settings.get("separator"):
            if "SplitText-PC36h" not in tweaks:
                tweaks["SplitText-PC36h"] = {}
            if settings.get("chunkSize"):
                tweaks["SplitText-PC36h"]["chunk_size"] = settings["chunkSize"]
            if settings.get("chunkOverlap"):
                tweaks["SplitText-PC36h"]["chunk_overlap"] = settings["chunkOverlap"]
            if settings.get("separator"):
                tweaks["SplitText-PC36h"]["separator"] = settings["separator"]
        if settings.get("embeddingModel"):
            if "OpenAIEmbeddings-joRJ6" not in tweaks:
                tweaks["OpenAIEmbeddings-joRJ6"] = {}
            tweaks["OpenAIEmbeddings-joRJ6"]["model"] = settings["embeddingModel"]

    jwt_token = user.jwt_token

    if jwt_token:
        from auth_context import set_auth_context
        set_auth_context(user.user_id, jwt_token)

    try:
        result = await langflow_file_service.run_ingestion_flow(
            file_paths=body.file_paths,
            file_tuples=file_tuples,
            jwt_token=jwt_token,
            session_id=body.session_id,
            tweaks=tweaks,
            owner=user.user_id,
            owner_name=user.name,
            owner_email=user.email,
            connector_type="local",
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def upload_and_ingest_user_file(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    settings_json: Optional[str] = Form(None, alias="settings"),
    tweaks_json: Optional[str] = Form(None, alias="tweaks"),
    delete_after_ingest: str = Form("true"),
    langflow_file_service=Depends(get_langflow_file_service),
    session_manager=Depends(get_session_manager),
    task_service=Depends(get_task_service),
    user: User = Depends(get_current_user),
):
    """Upload and ingest a file via Langflow (async background task)"""
    try:
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

        jwt_token = user.jwt_token
        content = await file.read()

        temp_dir = tempfile.gettempdir()
        safe_filename = file.filename.replace(" ", "_").replace("/", "_")
        temp_path = os.path.join(temp_dir, safe_filename)

        try:
            with open(temp_path, "wb") as f:
                f.write(content)

            task_id = await task_service.create_langflow_upload_task(
                user_id=user.user_id,
                file_paths=[temp_path],
                langflow_file_service=langflow_file_service,
                session_manager=session_manager,
                jwt_token=jwt_token,
                owner_name=user.name,
                owner_email=user.email,
                session_id=session_id,
                tweaks=tweaks,
                settings=settings,
                delete_after_ingest=delete_after_ingest.lower() == "true",
            )

            return JSONResponse(
                {
                    "task_id": task_id,
                    "message": f"Langflow upload task created for file '{file.filename}'",
                    "filename": file.filename,
                },
                status_code=202,
            )
        except Exception:
            from utils.file_utils import safe_unlink
            safe_unlink(temp_path)
            raise

    except Exception as e:
        logger.error("upload_and_ingest_user_file endpoint failed", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_user_files(
    body: DeleteFilesBody,
    langflow_file_service=Depends(get_langflow_file_service),
    user: User = Depends(get_current_user),
):
    """Delete files from Langflow's Files API"""
    errors = []
    for fid in body.file_ids:
        try:
            await langflow_file_service.delete_user_file(fid)
        except Exception as e:
            errors.append({"file_id": fid, "error": str(e)})

    status = 207 if errors else 200
    return JSONResponse(
        {
            "deleted": [fid for fid in body.file_ids if fid not in [e["file_id"] for e in errors]],
            "errors": errors,
        },
        status_code=status,
    )