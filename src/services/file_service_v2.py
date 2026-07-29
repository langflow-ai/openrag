"""
File service v2 — composite aggregation pagination.

Uses OpenSearch composite aggregation for  O(page_size) server-side
pagination. Only page_size buckets are processed per request regardless of
total file count.
"""

from typing import Any

from config.settings import get_index_name
from utils.logging_config import get_logger

logger = get_logger(__name__)

_COMPOSITE_SORT_FIELDS: dict[str, str] = {
    "filename": "filename",
    "file_size": "file_size",
    "mimetype": "mimetype",
    "indexed_time": "indexed_time",
    "connector_type": "connector_type",
    "embedding_model": "embedding_model",
}

# fall back to filename composite sort,then re-sort the returned page in python
_PYTHON_SORT_FIELDS = {"chunk_count", "owner"}


class FileServiceV2:
    """File-level views via composite aggregation (v2 — cursor pagination)."""

    def __init__(self, session_manager=None):
        self.session_manager = session_manager

    async def list_files(
        self,
        user_id: str,
        jwt_token: str = None,
        page: int = 1,
        page_size: int = 25,
        sort_by: str = "filename",
        sort_order: str = "asc",
        connector_type: str | None = None,
        mimetype: str | None = None,
        owner: str | None = None,
        search: str | None = None,
        after_key: dict | None = None,
    ) -> dict[str, Any]:
        """
        List files with server-side pagination via composite aggregation

        Cost is O(page_size) per request (as opposed to returning all unique file sizes from OpenSearch)
        Returns after_key for the next page (None when on the last page),
        plus an approximate total from a cardinality aggregation.
        """
        opensearch_client = self.session_manager.get_user_opensearch_client(user_id, jwt_token)

        query = self._build_filter_query(user_id, connector_type, mimetype, owner, search)
        total, is_approximate = await self._get_file_count(opensearch_client, query)

        use_python_sort = sort_by in _PYTHON_SORT_FIELDS
        composite_sort_field = "filename" if use_python_sort else _COMPOSITE_SORT_FIELDS.get(sort_by, "filename")

        agg_body = self._build_composite_aggregation(
            query=query,
            page_size=page_size,
            sort_field=composite_sort_field,
            sort_order=sort_order,
            after_key=after_key,
        )

        try:
            result = await opensearch_client.search(
                index=get_index_name(),
                body=agg_body,
            )
        except Exception as e:
            logger.error("Failed to list files (v2)", error=str(e))
            from utils.opensearch_utils import is_opensearch_auth_error

            if is_opensearch_auth_error(e):
                raise
            return {"files": [], "total": 0, "page": page, "page_size": page_size, "after_key": None}

        raw_bucket_count = len(
            result.get("aggregations", {}).get("files", {}).get("buckets", [])
        )
        files, next_after_key = self._parse_composite_buckets(result)

        if raw_bucket_count < page_size:  # final page, no after_key
            next_after_key = None

        if use_python_sort:
            reverse = sort_order.lower() == "desc"
            if sort_by == "chunk_count":
                files.sort(key=lambda f: f.get("chunk_count") or 0, reverse=reverse)
            elif sort_by == "owner":
                files.sort(key=lambda f: f.get("owner") or "", reverse=reverse)

        return {
            "files": files,
            "total": total,
            "is_approximate": is_approximate,
            "page": page,
            "page_size": page_size,
            "after_key": next_after_key,
        }

    async def search_files(
        self,
        user_id: str,
        jwt_token: str = None,
        query: str = "",
        page: int = 1,
        page_size: int = 25,
        connector_type: str | None = None,
        mimetype: str | None = None,
        owner: str | None = None,
        after_key: dict | None = None,
    ) -> dict[str, Any]:
        """Search files by name with fuzzy/prefix matching."""
        return await self.list_files(
            user_id=user_id,
            jwt_token=jwt_token,
            page=page,
            page_size=page_size,
            sort_by="filename",
            sort_order="asc",
            connector_type=connector_type,
            mimetype=mimetype,
            owner=owner,
            search=query,
            after_key=after_key,
        )

    def _build_filter_query(
        self,
        user_id: str,
        connector_type: str | None = None,
        mimetype: str | None = None,
        owner: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        must = []
        filter_clauses = []

        if connector_type:
            filter_clauses.append({"term": {"connector_type": connector_type}})
        if mimetype:
            filter_clauses.append({"term": {"mimetype": mimetype}})
        if owner:
            filter_clauses.append({"term": {"owner": owner}})

        if search:
            must.append(
                {
                    "bool": {
                        "should": [
                            {"wildcard": {"filename": {"value": f"*{search.lower()}*"}}},
                            {"prefix": {"filename": search.lower()}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

        query: dict[str, Any] = {"bool": {"filter": filter_clauses}}
        if must:
            query["bool"]["must"] = must
        return query

    def _build_composite_aggregation(
        self,
        query: dict[str, Any],
        page_size: int,
        sort_field: str,
        sort_order: str,
        after_key: dict | None,
    ) -> dict[str, Any]:
        composite: dict[str, Any] = {
            "size": page_size,
            "sources": [
                {
                    sort_field: {
                        "terms": {
                            "field": sort_field,
                            "order": sort_order,
                        }
                    }
                },
                *(
                    [{"filename_tiebreak": {"terms": {"field": "filename", "order": sort_order}}}]
                    if sort_field != "filename"
                    else []
                ),
            ],
        }

        if after_key:
            composite["after"] = after_key

        return {
            "size": 0,
            "query": query,
            "aggs": {
                "files": {
                    "composite": composite,
                    "aggs": {
                        "file_metadata": {
                            "top_hits": {
                                "size": 1,
                                "_source": [
                                    "document_id",
                                    "filename",
                                    "mimetype",
                                    "file_size",
                                    "source_url",
                                    "owner",
                                    "owner_name",
                                    "owner_email",
                                    "connector_type",
                                    "embedding_model",
                                    "embedding_dimensions",
                                    "indexed_time",
                                    "allowed_users",
                                    "allowed_groups",
                                    "allowed_principal_labels",
                                ],
                                "sort": [{"indexed_time": {"order": "desc"}}],
                            }
                        },
                        "chunk_count": {"value_count": {"field": "_id"}},
                    },
                }
            },
        }

    async def _get_file_count(self, opensearch_client: Any, query: dict[str, Any]) -> tuple[int, bool]:
        """Approximate unique-filename count via cardinality aggregation (O(1)).

        Returns (count, is_approximate).  is_approximate is always True on
        success (cardinality agg is inherently approximate) and False when the
        aggregation fails and 0 is returned as a fallback.
        """
        body = {
            "size": 0,
            "query": query,
            "aggs": {
                "file_count": {
                    "cardinality": {
                        "field": "filename",
                        "precision_threshold": 3000,
                    }
                }
            },
        }
        try:
            result = await opensearch_client.search(index=get_index_name(), body=body)
            return result.get("aggregations", {}).get("file_count", {}).get("value", 0), True
        except Exception as e:
            logger.warning("Failed to retrieve file count; pagination total will show 0", error=str(e))
            return 0, False

    def _parse_composite_buckets(
        self, result: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict | None]:
        """Parse composite agg buckets. Returns (files, next_after_key)."""
        agg = result.get("aggregations", {}).get("files", {})
        buckets = agg.get("buckets", [])
        next_after_key = agg.get("after_key")

        files = []
        for bucket in buckets:
            hits = bucket.get("file_metadata", {}).get("hits", {}).get("hits", [])
            if not hits:
                continue
            source = hits[0].get("_source", {})
            files.append(
                {
                    "filename": source.get("filename") or bucket["key"].get("filename", ""),
                    "document_id": source.get("document_id", ""),
                    "mimetype": source.get("mimetype", ""),
                    "file_size": source.get("file_size", 0),
                    "source_url": source.get("source_url", ""),
                    "owner": source.get("owner", ""),
                    "owner_name": source.get("owner_name", ""),
                    "owner_email": source.get("owner_email", ""),
                    "connector_type": source.get("connector_type", ""),
                    "embedding_model": source.get("embedding_model", ""),
                    "embedding_dimensions": source.get("embedding_dimensions"),
                    "indexed_time": source.get("indexed_time", ""),
                    "chunk_count": bucket.get("chunk_count", {}).get("value", 0),
                    "allowed_users": source.get("allowed_users", []),
                    "allowed_groups": source.get("allowed_groups", []),
                    "allowed_principal_labels": source.get("allowed_principal_labels", []),
                }
            )

        return files, next_after_key
