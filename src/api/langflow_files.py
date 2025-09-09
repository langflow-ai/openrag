from starlette.requests import Request
from starlette.responses import JSONResponse

from services.langflow_file_service import LangflowFileService
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def upload_user_file(
    request: Request, langflow_file_service: LangflowFileService, session_manager
):
    try:
        logger.debug("upload_user_file endpoint called")
        form = await request.form()
        upload_file = form.get("file")
        if upload_file is None:
            logger.error("No file provided in upload request")
            return JSONResponse({"error": "Missing file"}, status_code=400)

        logger.debug(
            "Processing file", filename=upload_file.filename, size=upload_file.size
        )

        # starlette UploadFile provides file-like; httpx needs (filename, file, content_type)
        content = await upload_file.read()
        file_tuple = (
            upload_file.filename,
            content,
            upload_file.content_type or "application/octet-stream",
        )

        jwt_token = getattr(request.state, "jwt_token", None)
        logger.debug("JWT token status", jwt_present=jwt_token is not None)

        logger.debug("Calling langflow_file_service.upload_user_file")
        result = await langflow_file_service.upload_user_file(file_tuple, jwt_token)
        logger.debug("Upload successful", result=result)
        return JSONResponse(result, status_code=201)
    except Exception as e:
        logger.error(
            "upload_user_file endpoint failed",
            error_type=type(e).__name__,
            error=str(e),
        )
        import traceback

        logger.error("Full traceback", traceback=traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)


async def run_ingestion(
    request: Request, langflow_file_service: LangflowFileService, session_manager
):
    try:
        payload = await request.json()
        file_ids = payload.get("file_ids")
        file_paths = payload.get("file_paths") or []
        session_id = payload.get("session_id")
        tweaks = payload.get("tweaks") or {}
        settings = payload.get("settings", {})

        # We assume file_paths is provided. If only file_ids are provided, client would need to resolve to paths via Files API (not implemented here).
        if not file_paths and not file_ids:
            return JSONResponse(
                {"error": "Provide file_paths or file_ids"}, status_code=400
            )

        # Convert UI settings to component tweaks using exact component IDs
        if settings:
            logger.debug("Applying ingestion settings", settings=settings)

            # Split Text component tweaks (SplitText-QIKhg)
            if (
                settings.get("chunkSize")
                or settings.get("chunkOverlap")
                or settings.get("separator")
            ):
                if "SplitText-QIKhg" not in tweaks:
                    tweaks["SplitText-QIKhg"] = {}
                if settings.get("chunkSize"):
                    tweaks["SplitText-QIKhg"]["chunk_size"] = settings["chunkSize"]
                if settings.get("chunkOverlap"):
                    tweaks["SplitText-QIKhg"]["chunk_overlap"] = settings[
                        "chunkOverlap"
                    ]
                if settings.get("separator"):
                    tweaks["SplitText-QIKhg"]["separator"] = settings["separator"]

            # OpenAI Embeddings component tweaks (OpenAIEmbeddings-joRJ6)
            if settings.get("embeddingModel"):
                if "OpenAIEmbeddings-joRJ6" not in tweaks:
                    tweaks["OpenAIEmbeddings-joRJ6"] = {}
                tweaks["OpenAIEmbeddings-joRJ6"]["model"] = settings["embeddingModel"]

            # Note: OpenSearch component tweaks not needed for ingestion
            # (search parameters are for retrieval, not document processing)

            logger.debug("Final tweaks with settings applied", tweaks=tweaks)
        # Include user JWT if available
        jwt_token = getattr(request.state, "jwt_token", None)

        # Extract user info from User object
        user = getattr(request.state, "user", None)
        user_id = user.user_id if user else None
        user_name = user.name if user else None
        user_email = user.email if user else None

        if jwt_token:
            # Set auth context for downstream services
            from auth_context import set_auth_context

            set_auth_context(user_id, jwt_token)

        result = await langflow_file_service.run_ingestion_flow(
            file_paths=file_paths or [],
            jwt_token=jwt_token,
            session_id=session_id,
            tweaks=tweaks,
            owner=user_id,
            owner_name=user_name,
            owner_email=user_email,
            connector_type="local",
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def upload_and_ingest_user_file(
    request: Request, langflow_file_service: LangflowFileService, session_manager
):
    """Combined upload and ingest endpoint - uploads file then runs ingestion"""
    try:
        logger.debug("upload_and_ingest_user_file endpoint called")
        form = await request.form()
        upload_file = form.get("file")
        if upload_file is None:
            logger.error("No file provided in upload_and_ingest request")
            return JSONResponse({"error": "Missing file"}, status_code=400)

        # Extract optional parameters
        session_id = form.get("session_id")
        settings_json = form.get("settings")
        tweaks_json = form.get("tweaks")
        delete_after_ingest = form.get("delete_after_ingest", "true").lower() == "true"

        # Parse JSON fields if provided
        settings = None
        tweaks = None
        
        if settings_json:
            try:
                import json
                settings = json.loads(settings_json)
            except json.JSONDecodeError as e:
                logger.error("Invalid settings JSON", error=str(e))
                return JSONResponse({"error": "Invalid settings JSON"}, status_code=400)

        if tweaks_json:
            try:
                import json
                tweaks = json.loads(tweaks_json)
            except json.JSONDecodeError as e:
                logger.error("Invalid tweaks JSON", error=str(e))
                return JSONResponse({"error": "Invalid tweaks JSON"}, status_code=400)

        logger.debug(
            "Processing file for combined upload and ingest",
            filename=upload_file.filename,
            size=upload_file.size,
            session_id=session_id,
            has_settings=bool(settings),
            has_tweaks=bool(tweaks),
            delete_after_ingest=delete_after_ingest
        )

        # Prepare file tuple for upload
        content = await upload_file.read()
        file_tuple = (
            upload_file.filename,
            content,
            upload_file.content_type or "application/octet-stream",
        )

        jwt_token = getattr(request.state, "jwt_token", None)
        logger.debug("JWT token status", jwt_present=jwt_token is not None)

        logger.debug("Calling langflow_file_service.upload_and_ingest_file")
        result = await langflow_file_service.upload_and_ingest_file(
            file_tuple=file_tuple,
            session_id=session_id,
            tweaks=tweaks,
            settings=settings,
            jwt_token=jwt_token,
            delete_after_ingest=delete_after_ingest
        )
        
        logger.debug("Upload and ingest successful", result=result)
        return JSONResponse(result, status_code=201)
        
    except Exception as e:
        logger.error(
            "upload_and_ingest_user_file endpoint failed",
            error_type=type(e).__name__,
            error=str(e),
        )
        import traceback
        logger.error("Full traceback", traceback=traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_user_files(
    request: Request, langflow_file_service: LangflowFileService, session_manager
):
    try:
        payload = await request.json()
        file_ids = payload.get("file_ids")
        if not file_ids or not isinstance(file_ids, list):
            return JSONResponse(
                {"error": "file_ids must be a non-empty list"}, status_code=400
            )

        errors = []
        for fid in file_ids:
            try:
                await langflow_file_service.delete_user_file(fid)
            except Exception as e:
                errors.append({"file_id": fid, "error": str(e)})

        status = 207 if errors else 200
        return JSONResponse(
            {
                "deleted": [
                    fid for fid in file_ids if fid not in [e["file_id"] for e in errors]
                ],
                "errors": errors,
            },
            status_code=status,
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
