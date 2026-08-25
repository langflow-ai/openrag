from fastapi import Depends, HTTPException, Query

from api.schemas.status import LogsResponse, StatusResponse
from api.status_utils import build_logs_response
from dependencies import require_api_key_permission
from services.status_service import aggregate_status
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def get_status_endpoint(
    user: User = Depends(require_api_key_permission("providers:read")),
) -> StatusResponse:
    """Aggregate component readiness. GET /v1/status"""
    try:
        return await aggregate_status()
    except Exception as e:
        logger.error("Failed to get status", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get status") from e


async def get_component_logs_endpoint(
    component: str,
    tail: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_api_key_permission("providers:read")),
) -> LogsResponse:
    """Return recent log entries for one component. GET /v1/status/{component}/logs

    The in-process ring buffer is the uniform source of truth for all four
    components.  A Langflow native-logs proxy was evaluated and dropped:
    the endpoint path, auth requirements, and response shape are unstable
    across Langflow versions (0.9.6 vs 0.11.2rc0+).
    """
    return build_logs_response(component, tail)
