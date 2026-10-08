from typing import Any, Literal

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config.settings import is_url_connector_enabled
from connectors.url.projection import get_source_manifest, list_page_manifests
from dependencies import (
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
    resultMode: Literal["chunks", "knowledge_sources", "website_pages"] = "chunks"

    model_config = {"populate_by_name": True}


def _website_page_chunk(page: dict[str, Any]) -> dict[str, Any]:
    """Adapt one OpenSearch page manifest to the child-page table shape."""
    return {
        "filename": page.get("filename") or page.get("canonical_url") or "Untitled page",
        "mimetype": page.get("mimetype") or "text/html",
        "page": 1,
        "text": "",
        "score": 0,
        "source_url": page.get("source_url") or page.get("canonical_url") or "",
        "file_size": page.get("file_size") or 0,
        "connector_type": "url",
        "document_id": page.get("content_document_id") or page.get("document_id"),
        "web_source_id": page.get("web_source_id"),
        "web_page_id": page.get("web_page_id"),
        "web_page_depth": page.get("web_page_depth") or 0,
        "canonical_url": page.get("canonical_url"),
        "status": page.get("status") or "active",
        "error": page.get("last_error"),
        "chunk_count": page.get("chunk_count") or 0,
        "embedding_model": page.get("embedding_model"),
        "embedding_dimensions": page.get("embedding_dimensions"),
    }


async def _website_page_search_result(
    body: SearchBody,
    user: User,
) -> dict[str, Any]:
    """List durable child-page manifests, including zero-chunk pages."""
    source_ids = body.filters.get("web_source_ids")
    if not isinstance(source_ids, list) or len(source_ids) != 1 or not source_ids[0]:
        raise HTTPException(422, "website_pages search requires one web_source_ids filter")
    source_id = source_ids[0]
    source = await get_source_manifest(source_id)
    if source is None or source.get("owner_id") != user.user_id:
        raise HTTPException(404, "Website source not found")

    pages = await list_page_manifests(source_id, body.query)
    results = [_website_page_chunk(page) for page in pages]
    return {"results": results, "total": len(results)}


async def search(
    body: SearchBody,
    search_service=Depends(get_search_service),
    user: User = Depends(require_permission("search:use")),
):
    """Search for documents"""
    try:
        if body.resultMode == "website_pages" and not is_url_connector_enabled():
            raise HTTPException(status_code=404, detail="Website connector is not enabled")

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

        if body.resultMode == "website_pages":
            result = await _website_page_search_result(body, user)
        else:
            result = await search_service.search(
                body.query,
                user_id=user.user_id,
                jwt_token=jwt_token,
                filters=body.filters,
                limit=body.limit,
                score_threshold=body.scoreThreshold,
            )
            if body.resultMode == "knowledge_sources":
                result["results"] = [
                    item for item in result.get("results", []) if not item.get("web_page_id")
                ]
                result["total"] = len(result["results"])
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
