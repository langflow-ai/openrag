"""Reset Flow API endpoints"""

from starlette.requests import Request
from starlette.responses import JSONResponse
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def reset_flow_endpoint(
    request: Request,
    chat_service,
):
    """Reset a Langflow flow by type (nudges, retrieval, or ingest)"""
    
    # Get flow type from path parameter
    flow_type = request.path_params.get("flow_type")
    
    if flow_type not in ["nudges", "retrieval", "ingest"]:
        return JSONResponse(
            {
                "success": False,
                "error": "Invalid flow type. Must be 'nudges', 'retrieval', or 'ingest'"
            },
            status_code=400
        )
    
    try:
        # Get user information from session for logging
        
        # Call the chat service to reset the flow
        result = await chat_service.reset_langflow_flow(flow_type)
        
        if result.get("success"):
            logger.info(
                f"Flow reset successful",
                flow_type=flow_type,
                flow_id=result.get("flow_id")
            )
            return JSONResponse(result, status_code=200)
        else:
            logger.error(
                f"Flow reset failed",
                flow_type=flow_type,
                error=result.get("error")
            )
            return JSONResponse(result, status_code=500)
            
    except ValueError as e:
        logger.error(f"Invalid request for flow reset", error=str(e))
        return JSONResponse(
            {
                "success": False,
                "error": str(e)
            },
            status_code=400
        )
    except Exception as e:
        logger.error(f"Unexpected error in flow reset", error=str(e))
        return JSONResponse(
            {
                "success": False,
                "error": f"Internal server error: {str(e)}"
            },
            status_code=500
        )
