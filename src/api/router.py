"""Router endpoints that automatically route based on configuration settings."""

from starlette.requests import Request
from starlette.responses import JSONResponse

from utils.logging_config import get_logger
from .upload_utils import extract_user_context, create_temp_files_from_form_files

logger = get_logger(__name__)


async def upload_ingest_router(
    request: Request, 
    document_service=None, 
    langflow_file_service=None, 
    session_manager=None,
    task_service=None
):
    """
    Router endpoint that automatically routes upload requests based on configuration.
    
    - If DISABLE_INGEST_WITH_LANGFLOW is True: uses traditional OpenRAG upload (/upload)
    - If DISABLE_INGEST_WITH_LANGFLOW is False (default): uses Langflow upload-ingest via task service
    
    This provides a single endpoint that users can call regardless of backend configuration.
    All langflow uploads are processed as background tasks for better scalability.
    """
    try:
        # Read setting at request time to avoid stale module-level values
        from config import settings as cfg
        disable_langflow_ingest = cfg.DISABLE_INGEST_WITH_LANGFLOW
        logger.debug("Router upload_ingest endpoint called", disable_langflow_ingest=disable_langflow_ingest)
        
        # Route based on configuration
        if disable_langflow_ingest:
            # Traditional OpenRAG path: create a background task via TaskService
            logger.debug("Routing to traditional OpenRAG upload via task service (async)")
            form = await request.form()
            upload_files = form.getlist("file")
            if not upload_files:
                return JSONResponse({"error": "Missing file"}, status_code=400)
            # Extract user context
            ctx = await extract_user_context(request)

            # Create temporary files
            temp_file_paths = await create_temp_files_from_form_files(upload_files)
            try:
                # Create traditional upload task for all files
                task_id = await task_service.create_upload_task(
                    ctx["owner_user_id"],
                    temp_file_paths,
                    jwt_token=ctx["jwt_token"],
                    owner_name=ctx["owner_name"],
                    owner_email=ctx["owner_email"],
                )
                return JSONResponse(
                    {
                        "task_id": task_id,
                        "message": f"Traditional upload task created for {len(upload_files)} file(s)",
                        "file_count": len(upload_files),
                    },
                    status_code=201,
                )
            except Exception:
                # Clean up temp files on error
                import os
                for p in temp_file_paths:
                    try:
                        if os.path.exists(p):
                            os.unlink(p)
                    except Exception:
                        pass
                raise
        else:
            # Route to Langflow upload-ingest via task service for async processing (202 + task_id)
            logger.debug("Routing to Langflow upload-ingest pipeline via task service (async)")
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
    request: Request, 
    langflow_file_service, 
    session_manager, 
    task_service
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

        # Get user/auth context (allows no-auth mode)
        ctx = await extract_user_context(request)
        user_id = ctx["owner_user_id"]
        user_name = ctx["owner_name"]
        user_email = ctx["owner_email"]
        jwt_token = ctx["jwt_token"]

        # Create temporary files for task processing
        import os
        temp_file_paths = []
        
        try:
            temp_file_paths = await create_temp_files_from_form_files(upload_files)

            logger.debug(
                "Created temporary files for task-based processing",
                file_count=len(temp_file_paths),
                user_id=user_id,
                has_settings=bool(settings),
                has_tweaks=bool(tweaks),
                delete_after_ingest=delete_after_ingest
            )

            # Create langflow upload task
            task_id = await task_service.create_langflow_upload_task(
                user_id=user_id,
                file_paths=temp_file_paths,
                langflow_file_service=langflow_file_service,
                session_manager=session_manager,
                jwt_token=jwt_token,
                owner_name=user_name,
                owner_email=user_email,
                session_id=session_id,
                tweaks=tweaks,
                settings=settings,
                delete_after_ingest=delete_after_ingest,
            )

            logger.debug("Langflow upload task created successfully", task_id=task_id)
            
            return JSONResponse({
                "task_id": task_id,
                "message": f"Langflow upload task created for {len(upload_files)} file(s)",
                "file_count": len(upload_files)
            }, status_code=201)
            
        except Exception:
            # Clean up temp files on error
            for temp_path in temp_file_paths:
                try:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                except Exception:
                    pass  # Ignore cleanup errors
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
