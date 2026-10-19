from typing import Any, Dict

from fastapi import Depends
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse
from utils.logging_config import get_logger
from utils.opensearch_utils import OpenSearchDiskSpaceError, DISK_SPACE_ERROR_MESSAGE

from dependencies import (
    get_search_service,
    get_session_manager,
    get_current_user,
    require_permission,
)
from session_manager import User

logger = get_logger(__name__)


class SearchBody(BaseModel):
    query: str
    filters: Dict[str, Any] = Field(default_factory=dict)
    limit: int = 10
    scoreThreshold: float = Field(default=0, alias="scoreThreshold")

    model_config = {"populate_by_name": True}


class SuggestBody(BaseModel):
    """Search-as-you-type request. Bounds are enforced server-side."""

    query: str = Field(max_length=200)
    filters: dict[str, Any] = Field(default_factory=dict)
    # False: cheap keyword phase for every debounced keystroke.
    # True: also run the semantic (embedding) search.
    semantic: bool = False
    scoreThreshold: float = Field(default=0, ge=0, le=100, alias="scoreThreshold")

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
    except OpenSearchDiskSpaceError:
        return JSONResponse({"error": DISK_SPACE_ERROR_MESSAGE}, status_code=507)
    except Exception as e:
        error_msg = str(e)
        if (
            "AuthenticationException" in error_msg
            or "access denied" in error_msg.lower()
        ):
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            return JSONResponse({"error": error_msg}, status_code=500)


async def suggest(
    body: SuggestBody,
    search_service=Depends(get_search_service),
    user: User = Depends(require_permission("search:use")),
):
    """Query completions, matching files and per-file previews."""
    try:
        result = await search_service.suggest(
            body.query,
            user_id=user.user_id,
            jwt_token=user.jwt_token,
            filters=body.filters,
            semantic=body.semantic,
            score_threshold=body.scoreThreshold,
        )
        if result.get("error"):
            logger.error("Search suggest failed", user_id=user.user_id, error=result["error"])
            return JSONResponse({"error": "Suggestions unavailable"}, status_code=502)
        return JSONResponse(result, status_code=200)
    except OpenSearchDiskSpaceError:
        return JSONResponse({"error": DISK_SPACE_ERROR_MESSAGE}, status_code=507)
    except Exception as e:
        # Detailed error stays server-side; clients get a generic message.
        logger.error("Search suggest failed", user_id=user.user_id, error=str(e))
        return JSONResponse({"error": "Suggestions unavailable"}, status_code=500)
