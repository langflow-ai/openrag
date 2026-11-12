from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from dependencies import get_chat_service, get_current_user, get_session_manager
from services.llm_gateway import LlmGatewayError
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _openrag_user_id(user: User) -> str:
    return getattr(user, "db_user_id", None) or user.user_id


def _gateway_error(exc: LlmGatewayError) -> JSONResponse:
    """Log internal gateway details and return the caller-safe message and status."""
    logger.error("Nudges LLM gateway error", status_code=exc.status_code, error=exc.detail)
    return JSONResponse({"error": exc.message}, status_code=exc.status_code)


class NudgesBody(BaseModel):
    filters: dict | None = None
    limit: int | None = None
    score_threshold: float | None = None


async def nudges_from_kb_endpoint(
    body: NudgesBody,
    chat_service=Depends(get_chat_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Get nudges for a user"""
    jwt_token = user.jwt_token
    storage_user_id = _openrag_user_id(user)

    try:
        result = await chat_service.nudges_chat(
            user.user_id,
            jwt_token,
            filters=body.filters,
            limit=body.limit,
            score_threshold=body.score_threshold,
            storage_user_id=storage_user_id,
            session_manager=session_manager,
        )
        return JSONResponse(result)
    except HTTPException:
        raise
    except LlmGatewayError as exc:
        return _gateway_error(exc)
    except Exception as e:
        return JSONResponse({"error": f"Failed to get nudges: {str(e)}"}, status_code=500)


async def nudges_from_chat_id_endpoint(
    chat_id: str,
    body: NudgesBody,
    chat_service=Depends(get_chat_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Get nudges for a user based on a previous conversation"""
    jwt_token = user.jwt_token
    storage_user_id = _openrag_user_id(user)

    try:
        from api.chat import _assert_owns

        await _assert_owns(chat_id, storage_user_id)
        result = await chat_service.nudges_chat(
            user.user_id,
            jwt_token,
            previous_response_id=chat_id,
            filters=body.filters,
            limit=body.limit,
            score_threshold=body.score_threshold,
            storage_user_id=storage_user_id,
            session_manager=session_manager,
        )
        return JSONResponse(result)
    except HTTPException:
        raise
    except LlmGatewayError as exc:
        return _gateway_error(exc)
    except Exception as e:
        return JSONResponse({"error": f"Failed to get nudges: {str(e)}"}, status_code=500)
