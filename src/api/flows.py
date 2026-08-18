"""Reset Flow API endpoints"""

from typing import Literal

from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from dependencies import get_flows_service, require_permission
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)

FlowType = Literal["nudges", "retrieval", "ingest"]


async def reset_flow_endpoint(
    flow_type: str,
    flows_service=Depends(get_flows_service),
    user: User = Depends(require_permission("config:write")),
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
        return JSONResponse({"success": False, "error": "Internal server error"}, status_code=500)


class BulkUpdateFlowsRequest(BaseModel):
    flow_types: list[str]
    backup_custom: bool = True


async def get_flows_updates_endpoint(
    flows_service=Depends(get_flows_service),
    user: User = Depends(require_permission("flows:read")),
):
    """Get available updates for core flows"""
    try:
        user_id = getattr(user, "db_user_id", None) or getattr(user, "user_id", None)
        updates = await flows_service.get_flows_updates_available(user_id=user_id)
        return JSONResponse({"success": True, "updates": updates}, status_code=200)
    except Exception as e:
        logger.error("Error getting flow updates", error=str(e))
        return JSONResponse({"success": False, "error": "Internal server error"}, status_code=500)


async def bulk_update_flows_endpoint(
    request: BulkUpdateFlowsRequest,
    flows_service=Depends(get_flows_service),
    user: User = Depends(require_permission("config:write")),
):
    """Bulk update multiple flows and optionally backup custom flows"""
    try:
        results = await flows_service.bulk_update_flows(request.flow_types, request.backup_custom)
        overall_success = all(r.get("success", False) for r in results)
        return JSONResponse({"success": overall_success, "results": results}, status_code=200)
    except Exception as e:
        logger.error("Error bulk updating flows", error=str(e))
        return JSONResponse({"success": False, "error": "Internal server error"}, status_code=500)


class DismissFlowsUpdateRequest(BaseModel):
    flow_types: list[str] | None = None


async def dismiss_flows_update_endpoint(
    request: DismissFlowsUpdateRequest | None = None,
    flows_service=Depends(get_flows_service),
    user: User = Depends(require_permission("flows:read")),
):
    """Dismiss available flow update notifications ephemerally in backend memory"""
    try:
        flow_types = request.flow_types if request else None
        user_id = getattr(user, "db_user_id", None) or getattr(user, "user_id", None)
        flows_service.dismiss_flows_updates(flow_types, user_id=user_id)
        return JSONResponse({"success": True}, status_code=200)
    except Exception as e:
        logger.error("Error dismissing flow updates", error=str(e))
        return JSONResponse({"success": False, "error": "Internal server error"}, status_code=500)
