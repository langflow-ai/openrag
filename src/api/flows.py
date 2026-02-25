"""Reset Flow API endpoints"""
from typing import Literal

from fastapi import Depends
from fastapi.responses import JSONResponse
from utils.logging_config import get_logger

from dependencies import get_flows_service, get_current_user
from session_manager import User

logger = get_logger(__name__)

FlowType = Literal["nudges", "retrieval", "ingest"]


async def reset_flow_endpoint(
    flow_type: str,
    flows_service=Depends(get_flows_service),
    user: User = Depends(get_current_user),
):
    """Reset a Langflow flow by type (nudges, retrieval, or ingest)"""
    if flow_type not in ["nudges", "retrieval", "ingest"]:
        return JSONResponse(
            {
                "success": False,
                "error": "Invalid flow type. Must be 'nudges', 'retrieval', or 'ingest'"
            },
            status_code=400
        )

    try:
        result = await flows_service.reset_langflow_flow(flow_type)

        if result.get("success"):
            logger.info(
                "Flow reset successful",
                flow_type=flow_type,
                flow_id=result.get("flow_id")
            )
            return JSONResponse(result, status_code=200)
        else:
            logger.error(
                "Flow reset failed",
                flow_type=flow_type,
                error=result.get("error")
            )
            return JSONResponse(result, status_code=500)

    except ValueError as e:
        logger.error("Invalid request for flow reset", error=str(e))
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except Exception as e:
        logger.error("Unexpected error in flow reset", error=str(e))
        return JSONResponse(
            {"success": False, "error": f"Internal server error: {str(e)}"},
            status_code=500
        )
