"""
Public API v1 Search endpoint.

Provides semantic search functionality.
Uses API key authentication.
"""

import re
from typing import Any

from fastapi import Depends
from fastapi.responses import JSONResponse
from opensearchpy.exceptions import AuthenticationException, AuthorizationException, RequestError
from pydantic import BaseModel, Field, field_validator

from api.v1._filter_resolution import merge_filter_overrides, resolve_filter_id
from auth_context import set_auth_context
from dependencies import (
    get_knowledge_filter_service,
    get_search_service,
    require_api_key_permission,
)
from services.search_service import (
    RAW_QUERY_MAX_SIZE,
    RawSearchQueryDepthError,
    RawSearchQueryError,
    RawSearchQuerySizeError,
    RawSearchScriptedQueryError,
    SearchAuthenticationError,
)
from session_manager import User
from utils.logging_config import get_logger
from utils.opensearch_utils import DISK_SPACE_ERROR_MESSAGE, OpenSearchDiskSpaceError

logger = get_logger(__name__)

# "0" | "1" | "2" | "AUTO" | "AUTO:<low>,<high>"
_FUZZINESS_RE = re.compile(r"^(0|1|2|AUTO(:\d+,\d+)?)$")

# Client-facing messages keyed by exception *type*, not by reading the
# exception's own message text - see RawSearchQueryError's docstring.
_RAW_QUERY_ERROR_MESSAGES: dict[type[RawSearchQueryError], str] = {
    RawSearchScriptedQueryError: "Scripted query clauses are not allowed.",
    RawSearchQuerySizeError: f"'size' must not exceed {RAW_QUERY_MAX_SIZE}.",
    RawSearchQueryDepthError: "Query is nested too deeply.",
}
_RAW_QUERY_ERROR_DEFAULT_MESSAGE = "Raw search query rejected by safety validation."


class SearchV1Body(BaseModel):
    query: str
    filters: dict[str, Any] | None = None
    limit: int = 10
    score_threshold: float = 0
    filter_id: str | None = None
    # OpenSearch fuzziness for the keyword-match clause. See the
    # openrag_search MCP tool description for accepted values.
    # Defaults to "AUTO:7,10".
    fuzziness: str | None = None

    @field_validator("fuzziness")
    @classmethod
    def _check_fuzziness(cls, v: str | None) -> str | None:
        if v is not None and not _FUZZINESS_RE.match(v):
            msg = 'fuzziness must be "0", "1", "2", "AUTO", or "AUTO:<low>,<high>"'
            raise ValueError(msg)
        return v


class RawSearchV1Body(BaseModel):
    query: dict[str, Any] | str
    filters: dict[str, Any] | None = None
    limit: int = 10
    score_threshold: float = 0
    filter_id: str | None = None


class RawSearchV1Response(BaseModel):
    """OpenSearch response shape returned by /v1/search/raw (embedding vectors stripped)."""

    took: int | None = None
    timed_out: bool | None = None
    hits: dict[str, Any] = Field(default_factory=dict)
    aggregations: dict[str, Any] | None = None


async def search_endpoint(
    body: SearchV1Body,
    search_service=Depends(get_search_service),
    user: User = Depends(require_api_key_permission("search:use")),
    knowledge_filter_service=Depends(get_knowledge_filter_service),
):
    """Perform semantic search on documents. POST /v1/search"""
    query = body.query.strip()
    if not query:
        return JSONResponse({"error": "Query is required"}, status_code=400)

    # API-key requests can arrive without a JWT. Set the auth context before
    # resolving filters so search_tool() can still identify the caller.
    set_auth_context(user.user_id, user.jwt_token)

    resolved_filters = body.filters
    resolved_limit = body.limit
    resolved_score_threshold = body.score_threshold
    if body.filter_id:
        resolved = await resolve_filter_id(
            body.filter_id,
            knowledge_filter_service,
            user_id=user.user_id,
            jwt_token=user.jwt_token,
        )
        resolved_filters, resolved_limit, resolved_score_threshold = merge_filter_overrides(
            resolved, body
        )

    logger.debug(
        "Public API search request",
        user_id=user.user_id,
        query=query,
        filters=resolved_filters,
        limit=resolved_limit,
        score_threshold=resolved_score_threshold,
        filter_id=body.filter_id,
    )

    try:
        result = await search_service.search(
            query,
            user_id=user.user_id,
            jwt_token=user.jwt_token,
            filters=resolved_filters or {},
            limit=resolved_limit,
            score_threshold=resolved_score_threshold,
            fuzziness=body.fuzziness,
        )

        results = [
            {
                "filename": item.get("filename"),
                "text": item.get("text"),
                "score": item.get("score"),
                "page": item.get("page"),
                "mimetype": item.get("mimetype"),
            }
            for item in result.get("results", [])
        ]

        return JSONResponse({"results": results})

    except OpenSearchDiskSpaceError as e:
        logger.error("Search blocked by disk space constraint", error=str(e), user_id=user.user_id)
        return JSONResponse({"error": DISK_SPACE_ERROR_MESSAGE}, status_code=507)
    except (AuthenticationException, AuthorizationException) as e:
        logger.error("Search access denied", error=str(e), user_id=user.user_id)
        return JSONResponse({"error": "Access denied"}, status_code=403)
    except Exception as e:
        logger.error("Search failed", error=str(e), user_id=user.user_id)
        return JSONResponse(
            {"error": "Search failed. Check server logs for details."}, status_code=500
        )


async def raw_search_endpoint(
    body: RawSearchV1Body,
    search_service=Depends(get_search_service),
    user: User = Depends(require_api_key_permission("search:use")),
    knowledge_filter_service=Depends(get_knowledge_filter_service),
):
    """Execute a raw OpenSearch DSL query against the knowledge base. POST /v1/search/raw

    Unlike /v1/search's hybrid semantic+keyword search, `query` is passed
    through as OpenSearch Query DSL (bool queries, aggregations, sort, etc.).
    Still runs through the caller's ACL-scoped OpenSearch client and strips
    embedding vectors from results.
    """
    query = body.query
    if isinstance(query, str) and not query.strip():
        return JSONResponse({"error": "Query is required"}, status_code=400)
    if not isinstance(query, (dict, str)):
        return JSONResponse(
            {"error": "query must be an OpenSearch DSL object or a string"}, status_code=400
        )

    # API-key requests can arrive without a JWT. Set the auth context before
    # resolving filters so raw_search() can still identify the caller.
    set_auth_context(user.user_id, user.jwt_token)

    resolved_filters = body.filters
    resolved_limit = body.limit
    resolved_score_threshold = body.score_threshold
    if body.filter_id:
        resolved = await resolve_filter_id(
            body.filter_id,
            knowledge_filter_service,
            user_id=user.user_id,
            jwt_token=user.jwt_token,
        )
        resolved_filters, resolved_limit, resolved_score_threshold = merge_filter_overrides(
            resolved, body
        )

    logger.debug(
        "Public API raw search request",
        user_id=user.user_id,
        filters=resolved_filters,
        limit=resolved_limit,
        score_threshold=resolved_score_threshold,
        filter_id=body.filter_id,
    )

    try:
        result = await search_service.raw_search(
            query,
            user_id=user.user_id,
            jwt_token=user.jwt_token,
            filters=resolved_filters or {},
            limit=resolved_limit,
            score_threshold=resolved_score_threshold,
        )
        return JSONResponse(result)

    except OpenSearchDiskSpaceError as e:
        logger.error(
            "Raw search blocked by disk space constraint", error=str(e), user_id=user.user_id
        )
        return JSONResponse({"error": DISK_SPACE_ERROR_MESSAGE}, status_code=507)
    except SearchAuthenticationError:
        logger.warning("Raw search rejected: no authenticated user", user_id=user.user_id)
        return JSONResponse({"error": "Authentication required"}, status_code=401)
    except RawSearchQueryError as e:
        # Dispatch on exception type, not its message: the message itself is
        # never read here, so no exception-derived value reaches the response.
        logger.warning("Raw search query rejected by safety validation", user_id=user.user_id)
        message = _RAW_QUERY_ERROR_MESSAGES.get(type(e), _RAW_QUERY_ERROR_DEFAULT_MESSAGE)
        return JSONResponse({"error": message}, status_code=400)
    except (AuthenticationException, AuthorizationException) as e:
        logger.error("Raw search access denied", error=str(e), user_id=user.user_id)
        return JSONResponse({"error": "Access denied"}, status_code=403)
    except RequestError as e:
        # OpenSearch itself rejected the query DSL (malformed/unsupported clause) -
        # this is the caller's fault, not a server failure.
        logger.error("Raw search query rejected by OpenSearch", error=str(e), user_id=user.user_id)
        return JSONResponse(
            {
                "error": "Raw search query was rejected by OpenSearch. Check server logs for details."
            },
            status_code=400,
        )
    except Exception as e:
        # Anything else (connection/transport errors, unexpected internal failures)
        # is a server-side problem, not something the caller's request can fix.
        logger.error("Raw search failed", error=str(e), user_id=user.user_id)
        return JSONResponse(
            {"error": "Raw search failed. Check server logs for details."}, status_code=500
        )
