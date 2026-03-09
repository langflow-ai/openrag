from typing import Optional

from fastapi import Depends
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from utils.logging_config import get_logger

from dependencies import get_chat_service, get_session_manager, get_current_user
from session_manager import User

logger = get_logger(__name__)


class NudgesBody(BaseModel):
    filters: Optional[dict] = None
    limit: Optional[int] = None
    score_threshold: Optional[float] = None


async def nudges_from_kb_endpoint(
    body: NudgesBody,
    chat_service=Depends(get_chat_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Get nudges for a user"""
    jwt_token = user.jwt_token

    try:
        result = await chat_service.langflow_nudges_chat(
            user.user_id,
            jwt_token,
            filters=body.filters,
            limit=body.limit,
            score_threshold=body.score_threshold,
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to get nudges: {str(e)}"}, status_code=500
        )


async def nudges_from_chat_id_endpoint(
    chat_id: str,
    body: NudgesBody,
    chat_service=Depends(get_chat_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Get nudges for a user based on a previous conversation"""
    jwt_token = user.jwt_token

    try:
        result = await chat_service.langflow_nudges_chat(
            user.user_id,
            jwt_token,
            previous_response_id=chat_id,
            filters=body.filters,
            limit=body.limit,
            score_threshold=body.score_threshold,
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to get nudges: {str(e)}"}, status_code=500
        )
