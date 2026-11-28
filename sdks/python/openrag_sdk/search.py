"""OpenRAG SDK search client."""

from typing import TYPE_CHECKING, Any, Literal

from .models import SearchFilters, SearchResponse, SearchResult, SearchWarning

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
        filter_id: str | None = None,
        search_mode: Literal["hybrid", "vector", "keyword"] = "hybrid",
    ) -> SearchResponse:
        """
        Perform semantic search on documents.

        Args:
            query: The search query text.
            filters: Optional filters (data_sources, document_types).
            limit: Maximum number of results (default 10).
            score_threshold: Minimum score threshold (default 0).
            filter_id: Optional knowledge filter ID to apply.
            search_mode: "hybrid" (default) runs vector and keyword search together,
                as chat does. "vector" or "keyword" runs only that half, to see which
                half finds or loses a document. Needs an OpenRAG server that supports
                it; older servers ignore the option and run hybrid search.

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

        if filter_id:
            body["filter_id"] = filter_id

        # Only sent when set, so default requests stay unchanged.
        if search_mode != "hybrid":
            body["search_mode"] = search_mode

        response = await self._client._request(
            "POST",
            "/api/v1/search",
            json=body,
        )

        data = response.json()
        return SearchResponse(
            results=[SearchResult(**r) for r in data.get("results", [])],
            warnings=[SearchWarning(**w) for w in data.get("warnings", [])],
        )
