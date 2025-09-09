from starlette.requests import Request
from starlette.responses import JSONResponse

from services.langflow_file_service import LangflowFileService
from session_manager import AnonymousUser
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def upload_user_file(
    request: Request, langflow_file_service: LangflowFileService, task_service, session_manager
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

        # Get user info for task management
        user = getattr(request.state, "user", None)
        user_id = getattr(user, "user_id", AnonymousUser().user_id)

        # Create processor for Langflow file upload
        from models.processors import LangflowFileProcessor
        processor = LangflowFileProcessor(  
            langflow_file_service=langflow_file_service,
            jwt_token=jwt_token,
        )

        # Create task for file upload
        logger.debug("Creating task for langflow file upload")
        task_id = await task_service.create_custom_task(
            user_id, [file_tuple], processor
        )

        logger.debug("Task created successfully", task_id=task_id)
        return JSONResponse({
            "task_id": task_id,
            "total_files": 1,
            "status": "accepted"
        }, status_code=201)
        
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
        if jwt_token:
            # Set auth context for downstream services
            from auth_context import set_auth_context

            user_id = getattr(request.state, "user_id", None)
            set_auth_context(user_id, jwt_token)

        result = await langflow_file_service.run_ingestion_flow(
            file_paths=file_paths or [],
            jwt_token=jwt_token,
            session_id=session_id,
            tweaks=tweaks,
        )
        return JSONResponse(result)
    except Exception as e:
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
