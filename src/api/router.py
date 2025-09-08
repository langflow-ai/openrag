"""Router endpoints that automatically route based on configuration settings."""

from starlette.requests import Request
from starlette.responses import JSONResponse

from config.settings import DISABLE_INGEST_WITH_LANGFLOW
from utils.logging_config import get_logger

# Import the actual endpoint implementations
from .upload import upload as traditional_upload
from .langflow_files import upload_and_ingest_user_file as langflow_upload_ingest

logger = get_logger(__name__)


async def upload_ingest_router(
    request: Request, 
    document_service=None, 
    langflow_file_service=None, 
    session_manager=None
):
    """
    Router endpoint that automatically routes upload requests based on configuration.
    
    - If DISABLE_INGEST_WITH_LANGFLOW is True: uses traditional OpenRAG upload (/upload)
    - If DISABLE_INGEST_WITH_LANGFLOW is False (default): uses Langflow upload-ingest (/langflow/upload_ingest)
    
    This provides a single endpoint that users can call regardless of backend configuration.
    """
    try:
        logger.debug(
            "Router upload_ingest endpoint called", 
            disable_langflow_ingest=DISABLE_INGEST_WITH_LANGFLOW
        )
        
        if DISABLE_INGEST_WITH_LANGFLOW:
            # Route to traditional OpenRAG upload
            logger.debug("Routing to traditional OpenRAG upload")
            return await traditional_upload(request, document_service, session_manager)
        else:
            # Route to Langflow upload and ingest
            logger.debug("Routing to Langflow upload-ingest pipeline")
            return await langflow_upload_ingest(request, langflow_file_service, session_manager)
            
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
