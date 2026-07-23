"""Reset Flow API endpoints"""

from typing import Literal

from fastapi import Depends
from fastapi.responses import JSONResponse

from dependencies import get_current_user, get_flows_service, require_permission
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)

FlowType = Literal["nudges", "retrieval", "ingest"]


async def reset_flow_endpoint(
    flow_type: str,
    flows_service=Depends(get_flows_service),
    user: User = Depends(require_permission("flows:edit")),
):
    """Reset a Langflow flow by type (nudges, retrieval, or ingest)"""
    if flow_type not in ["nudges", "retrieval", "ingest"]:
        return JSONResponse(
            {
                "success": False,
                "error": "Invalid flow type. Must be 'nudges', 'retrieval', or 'ingest'",
            },
            status_code=400,
        )

    try:
        result = await flows_service.reset_langflow_flow(flow_type)

        if result.get("success"):
            logger.info("Flow reset successful", flow_type=flow_type, flow_id=result.get("flow_id"))
            return JSONResponse(result, status_code=200)
        else:
            logger.error("Flow reset failed", flow_type=flow_type, error=result.get("error"))
            return JSONResponse(result, status_code=500)

    except ValueError as e:
        logger.error("Invalid request for flow reset", error=str(e))
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except Exception as e:
        logger.error("Unexpected error in flow reset", error=str(e))
        return JSONResponse(
            {"success": False, "error": f"Internal server error: {str(e)}"}, status_code=500
        )


from typing import List

from pydantic import BaseModel


class BulkUpdateFlowsRequest(BaseModel):
    flow_types: list[str]
    backup_custom: bool = True


async def get_flows_updates_endpoint(
    flows_service=Depends(get_flows_service),
    user: User = Depends(require_permission("flows:read")),
):
    """Get available updates for core flows"""
    try:
        updates = await flows_service.get_flows_updates_available()
        return JSONResponse({"success": True, "updates": updates}, status_code=200)
    except Exception as e:
        logger.error("Error getting flow updates", error=str(e))
        return JSONResponse(
            {"success": False, "error": f"Internal server error: {str(e)}"}, status_code=500
        )


async def bulk_update_flows_endpoint(
    request: BulkUpdateFlowsRequest,
    flows_service=Depends(get_flows_service),
    user: User = Depends(require_permission("flows:edit")),
):
    """Bulk update multiple flows and optionally backup custom flows"""
    try:
        results = await flows_service.bulk_update_flows(request.flow_types, request.backup_custom)
        return JSONResponse({"success": True, "results": results}, status_code=200)
    except Exception as e:
        logger.error("Error bulk updating flows", error=str(e))
        return JSONResponse(
            {"success": False, "error": f"Internal server error: {str(e)}"}, status_code=500
        )
