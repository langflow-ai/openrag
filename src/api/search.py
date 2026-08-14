from typing import Any, Dict

from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from dependencies import (
    get_current_user,
    get_search_service,
    get_session_manager,
    require_permission,
)
from session_manager import User
from utils.logging_config import get_logger
from utils.opensearch_utils import DISK_SPACE_ERROR_MESSAGE, OpenSearchDiskSpaceError

logger = get_logger(__name__)


class SearchBody(BaseModel):
    query: str
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = 10
    offset: int = Field(default=0, ge=0, description="Number of chunks to skip (for pagination)")
    scoreThreshold: float = Field(default=0, alias="scoreThreshold")

    model_config = {"populate_by_name": True}


async def search(
    body: SearchBody,
    search_service=Depends(get_search_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_permission("search:use")),
):
    """Search for documents"""
    try:
        jwt_token = user.jwt_token

        logger.debug(
            "Search API request",
            user_id=user.user_id,
            has_jwt_token=jwt_token is not None,
            query=body.query,
            filters=body.filters,
            limit=body.limit,
            offset=body.offset,
            score_threshold=body.scoreThreshold,
        )

        result = await search_service.search(
            body.query,
            user_id=user.user_id,
            jwt_token=jwt_token,
            filters=body.filters,
            limit=body.limit,
            offset=body.offset,
            score_threshold=body.scoreThreshold,
        )
        return JSONResponse(result, status_code=200)
    except OpenSearchDiskSpaceError:
        return JSONResponse({"error": DISK_SPACE_ERROR_MESSAGE}, status_code=507)
    except Exception as e:
        error_msg = str(e)
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            return JSONResponse({"error": error_msg}, status_code=500)
