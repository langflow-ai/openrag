"""OpenRAG SDK search client."""

from typing import TYPE_CHECKING, Any

import httpx

from .models import RawSearchResponse, SearchFilters, SearchResponse, SearchResult

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
        fuzziness: str = "AUTO:7,10",
    ) -> SearchResponse:
        """
        Perform semantic search on documents.

        Args:
            query: The search query text.
            filters: Optional filters (data_sources, document_types).
            limit: Maximum number of results (default 10).
            score_threshold: Minimum score threshold (default 0).
            filter_id: Optional knowledge filter ID to apply.
            fuzziness: OpenSearch fuzziness for the keyword-match clause.
                See the openrag_search MCP tool description for accepted
                values. Defaults to "AUTO:7,10".

        Returns:
            SearchResponse containing the search results.
        """
        body: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "score_threshold": score_threshold,
            "fuzziness": fuzziness,
        }

        if filters:
            if isinstance(filters, SearchFilters):
                body["filters"] = filters.model_dump(exclude_none=True)
            else:
                body["filters"] = filters

        if filter_id:
            body["filter_id"] = filter_id

        response = await self._client._request(
            "POST",
            "/api/v1/search",
            json=body,
        )

        data = response.json()
        return SearchResponse(
            results=[SearchResult(**r) for r in data.get("results", [])]
        )

    async def raw_query(
        self,
        query: dict[str, Any] | str,
        *,
        filters: SearchFilters | dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float = 0,
        filter_id: str | None = None,
    ) -> RawSearchResponse:
        """
        Execute a raw OpenSearch DSL query against the knowledge base.

        Unlike `query()`, which runs OpenRAG's hybrid semantic+keyword search,
        this passes `query` through as OpenSearch Query DSL (bool queries,
        aggregations, sort, etc.) for advanced use cases. Still enforces the
        caller's document-level ACLs and strips embedding vectors from results.

        Args:
            query: OpenSearch query DSL dict, or a JSON/plain-text string
                (falls back to a keyword match when it isn't valid JSON).
            filters: Optional filters (data_sources, document_types) merged
                in as OpenSearch filter clauses.
            limit: Result size cap, applied unless `query` already sets "size".
            score_threshold: Minimum `_score`, applied unless `query` already
                sets "min_score".
            filter_id: Optional knowledge filter ID to resolve and merge in.

        Returns:
            RawSearchResponse wrapping the OpenSearch response.
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

        response = await self._client._request(
            "POST",
            "/api/v1/search/raw",
            json=body,
        )

        return RawSearchResponse(**response.json())
