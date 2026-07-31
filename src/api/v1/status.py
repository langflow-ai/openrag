from fastapi import Depends, HTTPException

from api.schemas.status import StatusResponse
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

        raise HTTPException(status_code=500, detail="Failed to get status")
