from typing import Any, Dict

from fastapi import Depends
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse
from utils.logging_config import get_logger

from dependencies import get_search_service, get_session_manager, get_current_user
from session_manager import User

logger = get_logger(__name__)


class SearchBody(BaseModel):
    query: str
    filters: Dict[str, Any] = Field(default_factory=dict)
    limit: int = 10
    scoreThreshold: float = Field(default=0, alias="scoreThreshold")

    model_config = {"populate_by_name": True}


async def search(
    body: SearchBody,
    search_service=Depends(get_search_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Search for documents"""
    try:
        jwt_token = user.jwt_token

        logger.debug(
            "Search API request",
            user=str(user),
            user_id=user.user_id,
            has_jwt_token=jwt_token is not None,
            query=body.query,
            filters=body.filters,
            limit=body.limit,
            score_threshold=body.scoreThreshold,
        )

        result = await search_service.search(
            body.query,
            user_id=user.user_id,
            jwt_token=jwt_token,
            filters=body.filters,
            limit=body.limit,
            score_threshold=body.scoreThreshold,
        )
        return JSONResponse(result, status_code=200)
    except Exception as e:
        error_msg = str(e)
        if (
            "AuthenticationException" in error_msg
            or "access denied" in error_msg.lower()
        ):
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            return JSONResponse({"error": error_msg}, status_code=500)
