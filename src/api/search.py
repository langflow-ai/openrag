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

# OpenSearch's default result window caps a single ranked search at 10,000
# hits. Knowledge-source results are grouped after the ranked search, so use
# progressively larger candidate sets (up to that window) before applying the
# caller's result limit.
_MAX_KNOWLEDGE_SOURCE_CANDIDATES = 10_000


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


def _website_source_chunk(source: dict[str, Any], matching_page: dict[str, Any]) -> dict[str, Any]:
    """Represent a content-matching website page as its parent Knowledge row."""
    source_id = str(source["id"])
    return {
        "filename": source.get("filename") or source.get("name") or "Untitled website",
        "mimetype": source.get("mimetype") or "text/html",
        "page": matching_page.get("page"),
        "text": "",
        "highlights": matching_page.get("highlights", []),
        "score": matching_page.get("score", 0),
        "source_url": source.get("source_url") or source.get("starting_url") or "",
        "owner": source.get("owner") or source.get("owner_id"),
        "owner_name": source.get("owner_name", ""),
        "owner_email": source.get("owner_email", ""),
        "file_size": source.get("file_size", 0),
        "connector_type": "url",
        "embedding_model": source.get("embedding_model"),
        "embedding_provider": source.get("embedding_provider"),
        "embedding_space_id": source.get("embedding_space_id"),
        "embedding_dimensions": source.get("embedding_dimensions"),
        "allowed_users": source.get("allowed_users", []),
        "allowed_groups": source.get("allowed_groups", []),
        "allowed_principal_labels": source.get("allowed_principal_labels", []),
        "document_id": source.get("document_id"),
        "web_source_id": source_id,
        "web_child_count": source.get("web_child_count", 0),
        "chunk_count": source.get("chunk_count", 0),
        "canonical_url": source.get("starting_url"),
        "status": source.get("status", "active"),
        "error": source.get("last_error") or source.get("error"),
    }


async def _aggregate_website_page_matches(
    results: list[dict[str, Any]], user: User
) -> list[dict[str, Any]]:
    """Replace matching website-page chunks with their parent source manifests.

    A website source manifest has no body text or embedding. Its indexed child
    pages do, so excluding child chunks before ranking means content searches
    can never find their parent source. Keep the page hit's rank and score,
    but return the parent projection expected by the Knowledge table.
    """
    ranked_results: list[tuple[int, dict[str, Any]]] = []
    page_matches: dict[str, tuple[int, dict[str, Any]]] = {}
    direct_source_hits: dict[str, tuple[int, dict[str, Any]]] = {}

    for rank, result in enumerate(results):
        source_id = result.get("web_source_id")
        if result.get("web_page_id") and source_id:
            page_matches.setdefault(str(source_id), (rank, result))
        elif result.get("connector_type") == "url" and source_id:
            direct_source_hits[str(source_id)] = (rank, result)
        else:
            ranked_results.append((rank, result))

    for source_id, (page_rank, page_match) in page_matches.items():
        source = await get_source_manifest(source_id)
        if source is None or source.get("owner_id") != user.user_id or source.get("deleting"):
            continue
        direct_hit = direct_source_hits.pop(source_id, None)
        rank = min(page_rank, direct_hit[0]) if direct_hit else page_rank
        source_result = _website_source_chunk(source, page_match)
        if direct_hit and (direct_score := direct_hit[1].get("score")) is not None:
            source_result["score"] = max(source_result["score"] or 0, direct_score)
        ranked_results.append((rank, source_result))

    ranked_results.extend(direct_source_hits.values())
    return [result for _, result in sorted(ranked_results, key=lambda item: item[0])]


async def _website_page_search_result(
    body: SearchBody,
    user: User,
    search_service=None,
) -> dict[str, Any]:
    """Search durable child-page manifests, including zero-chunk pages.

    Manifest matches cover page URL and title, while indexed chunks cover page
    content. Both are projected from the manifest so page-table rows always
    carry durable page metadata such as status and page ID.
    """
    source_ids = body.filters.get("web_source_ids")
    if not isinstance(source_ids, list) or len(source_ids) != 1 or not source_ids[0]:
        raise HTTPException(422, "website_pages search requires one web_source_ids filter")
    source_id = source_ids[0]
    source = await get_source_manifest(source_id)
    if source is None or source.get("owner_id") != user.user_id:
        raise HTTPException(404, "Website source not found")

    query = body.query.strip()
    all_pages = await list_page_manifests(source_id)
    matching_pages = (
        await list_page_manifests(source_id, query) if query and query != "*" else all_pages
    )
    pages_by_id = {str(page["web_page_id"]): page for page in all_pages if page.get("web_page_id")}
    results_by_page_id = {
        str(page["web_page_id"]): _website_page_chunk(page)
        for page in matching_pages
        if page.get("web_page_id")
    }

    if query and query != "*" and search_service is not None:
        content_matches = await search_service.search(
            body.query,
            user_id=user.user_id,
            jwt_token=user.jwt_token,
            filters=body.filters,
            limit=body.limit,
            score_threshold=body.scoreThreshold,
            result_mode="chunks",
        )
        for match in content_matches.get("results", []):
            page_id = match.get("web_page_id")
            page = pages_by_id.get(str(page_id)) if page_id else None
            if page is None:
                continue
            result = results_by_page_id.setdefault(str(page_id), _website_page_chunk(page))
            if (score := match.get("score")) is not None and score > result["score"]:
                result["score"] = score
                result["highlights"] = match.get("highlights", [])

    results = list(results_by_page_id.values())
    return {"results": results, "total": len(results)}


async def _search_knowledge_sources(
    body: SearchBody,
    search_service: Any,
    user: User,
) -> dict[str, Any]:
    """Gather and group enough ranked hits before enforcing ``body.limit``."""
    requested_limit = max(body.limit, 0)
    candidate_limit = min(max(requested_limit * 10, 100), _MAX_KNOWLEDGE_SOURCE_CANDIDATES)

    while True:
        result = await search_service.search(
            body.query,
            user_id=user.user_id,
            jwt_token=user.jwt_token,
            filters=body.filters,
            limit=candidate_limit,
            score_threshold=body.scoreThreshold,
            result_mode=body.resultMode,
        )
        raw_results = result.get("results", [])
        grouped_results = await _aggregate_website_page_matches(raw_results, user)

        if (
            len(grouped_results) >= requested_limit
            or len(raw_results) < candidate_limit
            or candidate_limit == _MAX_KNOWLEDGE_SOURCE_CANDIDATES
        ):
            result["results"] = grouped_results[:requested_limit]
            result["total"] = len(result["results"])
            return result

        candidate_limit = min(candidate_limit * 2, _MAX_KNOWLEDGE_SOURCE_CANDIDATES)


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
            result = await _website_page_search_result(body, user, search_service)
        elif body.resultMode == "knowledge_sources":
            result = await _search_knowledge_sources(body, search_service, user)
        else:
            result = await search_service.search(
                body.query,
                user_id=user.user_id,
                jwt_token=jwt_token,
                filters=body.filters,
                limit=body.limit,
                score_threshold=body.scoreThreshold,
                result_mode=body.resultMode,
            )
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
