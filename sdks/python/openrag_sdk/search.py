"""OpenRAG SDK search client."""

from typing import TYPE_CHECKING, Any

import httpx

from .models import SearchFilters, SearchResponse, SearchResult

if TYPE_CHECKING:
    from .client import OpenRAGClient


class SearchClient:
    """Client for search operations."""

    def __init__(self, client: "OpenRAGClient"):
        self._client = client

    async def query(
        self,
        query: str,
        *,
        filters: SearchFilters | dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float = 0,
    ) -> SearchResponse:
        """
        Perform semantic search on documents.

        Args:
            query: The search query text.
            filters: Optional filters (data_sources, document_types).
            limit: Maximum number of results (default 10).
            score_threshold: Minimum score threshold (default 0).

        Returns:
            SearchResponse containing the search results.
        """
        body: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "score_threshold": score_threshold,
        }

        if filters:
            if isinstance(filters, SearchFilters):
                body["filters"] = filters.model_dump(exclude_none=True)
            else:
                body["filters"] = filters

        response = await self._client._request(
            "POST",
            "/api/v1/search",
            json=body,
        )

        data = response.json()
        return SearchResponse(
            results=[SearchResult(**r) for r in data.get("results", [])]
        )
