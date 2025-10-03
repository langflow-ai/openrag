"""Router endpoints that automatically route based on configuration settings."""

from starlette.requests import Request
from starlette.responses import JSONResponse

from config.settings import DISABLE_INGEST_WITH_LANGFLOW
from utils.logging_config import get_logger

# Import the actual endpoint implementations
from .upload import upload as traditional_upload

logger = get_logger(__name__)


async def upload_ingest_router(
    request: Request,
    document_service=None,
    langflow_file_service=None,
    session_manager=None,
    task_service=None,
):
    """
    Router endpoint that automatically routes upload requests based on configuration.

    - If DISABLE_INGEST_WITH_LANGFLOW is True: uses traditional OpenRAG upload (/upload)
    - If DISABLE_INGEST_WITH_LANGFLOW is False (default): uses Langflow upload-ingest via task service

    This provides a single endpoint that users can call regardless of backend configuration.
    All langflow uploads are processed as background tasks for better scalability.
    """
    try:
        logger.debug(
            "Router upload_ingest endpoint called",
            disable_langflow_ingest=DISABLE_INGEST_WITH_LANGFLOW,
        )

        # Route based on configuration
        if DISABLE_INGEST_WITH_LANGFLOW:
            # Route to traditional OpenRAG upload
            logger.debug("Routing to traditional OpenRAG upload")
            return await traditional_upload(request, document_service, session_manager)
        else:
            # Route to Langflow upload and ingest using task service
            logger.debug("Routing to Langflow upload-ingest pipeline via task service")
            return await langflow_upload_ingest_task(
                request, langflow_file_service, session_manager, task_service
            )

    except Exception as e:
        logger.error("Error in upload_ingest_router", error=str(e))
        error_msg = str(e)
        if (
            "AuthenticationException" in error_msg
            or "access denied" in error_msg.lower()
        ):
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            return JSONResponse({"error": error_msg}, status_code=500)


async def langflow_upload_ingest_task(
    request: Request, langflow_file_service, session_manager, task_service
):
    """Task-based langflow upload and ingest for single/multiple files"""
    try:
        logger.debug("Task-based langflow upload_ingest endpoint called")
        form = await request.form()
        upload_files = form.getlist("file")

        if not upload_files or len(upload_files) == 0:
            logger.error("No files provided in task-based upload request")
            return JSONResponse({"error": "Missing files"}, status_code=400)

        # Extract optional parameters
        session_id = form.get("session_id")
        settings_json = form.get("settings")
        tweaks_json = form.get("tweaks")
        delete_after_ingest = form.get("delete_after_ingest", "true").lower() == "true"
        replace_duplicates = form.get("replace_duplicates", "false").lower() == "true"

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

        # Get user info from request state
        user = getattr(request.state, "user", None)
        user_id = user.user_id if user else None
        user_name = user.name if user else None
        user_email = user.email if user else None
        jwt_token = getattr(request.state, "jwt_token", None)

        if not user_id:
            return JSONResponse(
                {"error": "User authentication required"}, status_code=401
            )

        # Create temporary files for task processing
        import tempfile
        import os

        temp_file_paths = []
        original_filenames = []

        try:
            # Create temp directory reference once
            temp_dir = tempfile.gettempdir()

            for upload_file in upload_files:
                # Read file content
                content = await upload_file.read()

                # Store ORIGINAL filename (not transformed)
                original_filenames.append(upload_file.filename)

                # Create temporary file with TRANSFORMED filename for filesystem safety
                # Transform: spaces and / to underscore
                safe_filename = upload_file.filename.replace(" ", "_").replace("/", "_")
                temp_path = os.path.join(temp_dir, safe_filename)

                # Write content to temp file
                with open(temp_path, "wb") as temp_file:
                    temp_file.write(content)

                temp_file_paths.append(temp_path)

            logger.debug(
                "Created temporary files for task-based processing",
                file_count=len(temp_file_paths),
                user_id=user_id,
                has_settings=bool(settings),
                has_tweaks=bool(tweaks),
                delete_after_ingest=delete_after_ingest,
            )

            # Create langflow upload task
            logger.debug(
                f"Preparing to create langflow upload task: tweaks={tweaks}, settings={settings}, jwt_token={jwt_token}, user_name={user_name}, user_email={user_email}, session_id={session_id}, delete_after_ingest={delete_after_ingest}, temp_file_paths={temp_file_paths}",
            )
            # Create a map between temp_file_paths and original_filenames
            file_path_to_original_filename = dict(zip(temp_file_paths, original_filenames))
            logger.debug(
                f"File path to original filename map: {file_path_to_original_filename}",
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
                delete_after_ingest=delete_after_ingest,
                replace_duplicates=replace_duplicates,
            )

            logger.debug("Langflow upload task created successfully", task_id=task_id)

            return JSONResponse(
                {
                    "task_id": task_id,
                    "message": f"Langflow upload task created for {len(upload_files)} file(s)",
                    "file_count": len(upload_files),
                },
                status_code=202,
            )  # 202 Accepted for async processing

        except Exception:
            # Clean up temp files on error
            from utils.file_utils import safe_unlink

            for temp_path in temp_file_paths:
                safe_unlink(temp_path)
            raise

    except Exception as e:
        logger.error(
            "Task-based langflow upload_ingest endpoint failed",
            error_type=type(e).__name__,
            error=str(e),
        )
        import traceback

        logger.error("Full traceback", traceback=traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)
