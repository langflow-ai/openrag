from typing import Any, Literal

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.website_source import WebsitePage, WebsiteSource
from dependencies import (
    get_db_session,
    get_search_service,
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
    scoreThreshold: float = Field(default=0, alias="scoreThreshold")
    resultMode: Literal["chunks", "website_pages"] = "chunks"

    model_config = {"populate_by_name": True}


def _website_page_chunk(page: WebsitePage, source_id: str) -> dict[str, Any]:
    """Adapt persisted page state to the search result shape used by the table."""
    return {
        "filename": page.title,
        "mimetype": page.content_type or "text/html",
        "page": 1,
        "text": "",
        "score": 0,
        "source_url": page.final_url or page.canonical_url,
        "file_size": page.byte_size,
        "connector_type": "url",
        "document_id": page.document_id,
        "web_source_id": source_id,
        "web_page_id": page.id,
        "web_page_depth": page.depth,
        "canonical_url": page.canonical_url,
        "status": page.status,
        "error": page.last_error,
        "chunk_count": page.chunk_count,
    }


async def _website_page_search_result(
    result: dict[str, Any],
    body: SearchBody,
    session: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """Hydrate URL search hits with page state, including zero-chunk rows."""
    source_ids = body.filters.get("web_source_ids")
    if not isinstance(source_ids, list) or len(source_ids) != 1 or not source_ids[0]:
        raise HTTPException(422, "website_pages search requires one web_source_ids filter")
    source_id = source_ids[0]
    source = await session.get(WebsiteSource, source_id)
    if source is None or source.owner_id != user.user_id:
        raise HTTPException(404, "Website source not found")

    pages = (
        (await session.execute(select(WebsitePage).where(WebsitePage.web_source_id == source_id)))
        .scalars()
        .all()
    )
    pages_by_document = {page.document_id: page for page in pages}
    hits_by_document: dict[str, list[dict[str, Any]]] = {}
    for chunk in result.get("results", []):
        document_id = chunk.get("document_id")
        if document_id in pages_by_document:
            hits_by_document.setdefault(document_id, []).append(chunk)

    wildcard = body.query.strip() in {"", "*"}
    visible_document_ids = set(pages_by_document) if wildcard else set(hits_by_document)
    hydrated_chunks: list[dict[str, Any]] = []
    for document_id in visible_document_ids:
        page = pages_by_document[document_id]
        page_chunk = _website_page_chunk(page, source_id)
        page_hits = hits_by_document.get(document_id, [])
        if page_hits:
            metadata = {
                key: page_chunk[key]
                for key in (
                    "filename",
                    "mimetype",
                    "source_url",
                    "file_size",
                    "connector_type",
                    "document_id",
                    "web_source_id",
                    "web_page_id",
                    "web_page_depth",
                    "canonical_url",
                    "status",
                    "error",
                    "chunk_count",
                )
            }
            hydrated_chunks.extend([{**chunk, **metadata} for chunk in page_hits])
        else:
            hydrated_chunks.append(page_chunk)

    return {**result, "results": hydrated_chunks, "total": len(hydrated_chunks)}


async def search(
    body: SearchBody,
    search_service=Depends(get_search_service),
    session: AsyncSession = Depends(get_db_session),
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
        if body.resultMode == "website_pages":
            result = await _website_page_search_result(result, body, session, user)
        return JSONResponse(result, status_code=200)
    except HTTPException:
        raise
    except OpenSearchDiskSpaceError:
        return JSONResponse({"error": DISK_SPACE_ERROR_MESSAGE}, status_code=507)
    except Exception as e:
        error_msg = str(e)
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            return JSONResponse({"error": error_msg}, status_code=500)
