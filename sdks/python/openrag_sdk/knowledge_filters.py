"""OpenRAG SDK knowledge filters client."""

import json
from typing import TYPE_CHECKING, Any

from .models import (
    CreateKnowledgeFilterOptions,
    CreateKnowledgeFilterResponse,
    DeleteKnowledgeFilterResponse,
    GetKnowledgeFilterResponse,
    KnowledgeFilter,
    KnowledgeFilterQueryData,
    KnowledgeFilterSearchResponse,
    UpdateKnowledgeFilterOptions,
)

if TYPE_CHECKING:
    from .client import OpenRAGClient


class KnowledgeFiltersClient:
    """Client for knowledge filter operations."""

    def __init__(self, client: "OpenRAGClient"):
        self._client = client

    async def create(
        self,
        options: CreateKnowledgeFilterOptions | dict[str, Any],
    ) -> CreateKnowledgeFilterResponse:
        """
        Create a new knowledge filter.

        Args:
            options: The filter options including name and query_data.

        Returns:
            The created filter response with ID.
        """
        if isinstance(options, CreateKnowledgeFilterOptions):
            name = options.name
            description = options.description or ""
            query_data = options.query_data
        else:
            name = options["name"]
            description = options.get("description", "")
            query_data = options.get("query_data") or options.get("queryData", {})

        # Convert query_data to JSON string if it's a model
        if isinstance(query_data, KnowledgeFilterQueryData):
            query_data_str = query_data.model_dump_json(by_alias=True, exclude_none=True)
        elif isinstance(query_data, dict):
            query_data_str = json.dumps(query_data)
        else:
            query_data_str = str(query_data)

        body = {
            "name": name,
            "description": description,
            "queryData": query_data_str,
        }

        response = await self._client._request(
            "POST",
            "/api/v1/knowledge-filters",
            json=body,
        )

        data = response.json()
        return CreateKnowledgeFilterResponse(
            success=data.get("success", False),
            id=data.get("id"),
            error=data.get("error"),
        )

    async def search(
        self,
        query: str = "",
        limit: int = 20,
    ) -> list[KnowledgeFilter]:
        """
        Search for knowledge filters by name, description, or query content.

        Args:
            query: Optional search query text.
            limit: Maximum number of results (default 20).

        Returns:
            List of matching knowledge filters.
        """
        body = {
            "query": query,
            "limit": limit,
        }

        response = await self._client._request(
            "POST",
            "/api/v1/knowledge-filters/search",
            json=body,
        )

        data = response.json()
        if not data.get("success") or not data.get("filters"):
            return []

        return [self._parse_filter(f) for f in data["filters"]]

    async def get(self, filter_id: str) -> KnowledgeFilter | None:
        """
        Get a specific knowledge filter by ID.

        Args:
            filter_id: The ID of the filter to retrieve.

        Returns:
            The knowledge filter or None if not found.
        """
        try:
            response = await self._client._request(
                "GET",
                f"/api/v1/knowledge-filters/{filter_id}",
            )

            data = response.json()
            if not data.get("success") or not data.get("filter"):
                return None

            return self._parse_filter(data["filter"])
        except Exception:
            # Filter not found or other error
            return None

    async def update(
        self,
        filter_id: str,
        options: UpdateKnowledgeFilterOptions | dict[str, Any],
    ) -> bool:
        """
        Update an existing knowledge filter.

        Args:
            filter_id: The ID of the filter to update.
            options: The fields to update.

        Returns:
            Success status.
        """
        body: dict[str, Any] = {}

        if isinstance(options, UpdateKnowledgeFilterOptions):
            if options.name is not None:
                body["name"] = options.name
            if options.description is not None:
                body["description"] = options.description
            if options.query_data is not None:
                body["queryData"] = options.query_data.model_dump_json(
                    by_alias=True, exclude_none=True
                )
        else:
            if "name" in options:
                body["name"] = options["name"]
            if "description" in options:
                body["description"] = options["description"]
            query_data = options.get("query_data") or options.get("queryData")
            if query_data is not None:
                if isinstance(query_data, KnowledgeFilterQueryData):
                    body["queryData"] = query_data.model_dump_json(
                        by_alias=True, exclude_none=True
                    )
                elif isinstance(query_data, dict):
                    body["queryData"] = json.dumps(query_data)
                else:
                    body["queryData"] = str(query_data)

        response = await self._client._request(
            "PUT",
            f"/api/v1/knowledge-filters/{filter_id}",
            json=body,
        )

        data = response.json()
        return data.get("success", False)

    async def delete(self, filter_id: str) -> bool:
        """
        Delete a knowledge filter.

        Args:
            filter_id: The ID of the filter to delete.

        Returns:
            Success status.
        """
        response = await self._client._request(
            "DELETE",
            f"/api/v1/knowledge-filters/{filter_id}",
        )

        data = response.json()
        return data.get("success", False)

    def _parse_filter(self, data: dict[str, Any]) -> KnowledgeFilter:
        """Parse a filter from API response, handling JSON-stringified query_data."""
        query_data = data.get("query_data") or data.get("queryData")
        if isinstance(query_data, str):
            try:
                query_data = json.loads(query_data)
            except json.JSONDecodeError:
                query_data = {}

        parsed_query_data = None
        if query_data:
            parsed_query_data = KnowledgeFilterQueryData(
                query=query_data.get("query"),
                filters=query_data.get("filters"),
                limit=query_data.get("limit"),
                score_threshold=query_data.get("scoreThreshold"),
                color=query_data.get("color"),
                icon=query_data.get("icon"),
            )

        return KnowledgeFilter(
            id=data["id"],
            name=data["name"],
            description=data.get("description"),
            query_data=parsed_query_data,
            owner=data.get("owner"),
            created_at=data.get("created_at") or data.get("createdAt"),
            updated_at=data.get("updated_at") or data.get("updatedAt"),
        )
