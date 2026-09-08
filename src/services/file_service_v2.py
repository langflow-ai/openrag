"""
File service v2 — composite aggregation pagination.

Uses OpenSearch composite aggregation for  O(page_size) server-side
pagination. Only page_size buckets are processed per request regardless of
total file count.

Sort-field notes
----------------
* Fields in _COMPOSITE_SORT_FIELDS are handled entirely by the composite agg —
  ordering is globally correct and cursor-paginated.
* "owner" is a real keyword field so it lives in _COMPOSITE_SORT_FIELDS.
* "chunk_count" is a derived metric (value_count sub-agg).  Composite aggs
  cannot order by sub-aggregation metrics, so sorting by chunk_count falls back
  to a classic terms aggregation sorted by the sub-agg, with offset-based
  pagination (_build_terms_aggregation_for_chunk_count).  This is O(from+size)
  at the shard level but gives a globally correct sort.
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
    "owner": "owner",
}


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
        connector_type: list[str] | None = None,
        mimetype: list[str] | None = None,
        owner: list[str] | None = None,
        search: str | None = None,
        after_key: dict | None = None,
        data_sources: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        List files with server-side pagination via composite aggregation.

        Cost is O(page_size) per request (as opposed to returning all unique
        file sizes from OpenSearch).  Returns after_key for the next page
        (None when on the last page), plus an approximate total from a
        cardinality aggregation.

        Exception: when sort_by="chunk_count" a terms aggregation is used
        instead (composite aggs cannot order by sub-agg metrics).  Pagination
        is offset-based in that path; after_key is always None.
        """
        opensearch_client = self.session_manager.get_user_opensearch_client(user_id, jwt_token)

        query = self._build_filter_query(
            user_id, connector_type, mimetype, owner, search, data_sources
        )
        total, is_approximate = await self._get_file_count(opensearch_client, query)

        if sort_by == "chunk_count":
            return await self._list_files_by_chunk_count(
                opensearch_client=opensearch_client,
                query=query,
                page=page,
                page_size=page_size,
                sort_order=sort_order,
                total=total,
                is_approximate=is_approximate,
            )

        if page > 1 and after_key is None:
            return {
                "files": [],
                "total": total,
                "is_approximate": is_approximate,
                "page": page,
                "page_size": page_size,
                "after_key": None,
            }

        composite_sort_field = _COMPOSITE_SORT_FIELDS.get(sort_by, "filename")

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
            return {
                "files": [],
                "total": 0,
                "is_approximate": False,
                "page": page,
                "page_size": page_size,
                "after_key": None,
            }

        raw_bucket_count = len(result.get("aggregations", {}).get("files", {}).get("buckets", []))
        files, next_after_key = self._parse_composite_buckets(result)

        if raw_bucket_count < page_size:  # final page, no after_key
            next_after_key = None

        return {
            "files": files,
            "total": total,
            "is_approximate": is_approximate,
            "page": page,
            "page_size": page_size,
            "after_key": next_after_key,
        }

    async def _list_files_by_chunk_count(
        self,
        opensearch_client: Any,
        query: dict[str, Any],
        page: int,
        page_size: int,
        sort_order: str,
        total: int,
        is_approximate: bool,
    ) -> dict[str, Any]:
        """
        List files sorted globally by chunk_count using a terms aggregation.

        Terms aggs support ordering by sub-aggregation metrics, which composite
        aggs do not.  Pagination is offset-based (from = (page-1)*page_size).
        """
        offset = (page - 1) * page_size
        agg_body = self._build_terms_aggregation_for_chunk_count(
            query=query,
            page_size=page_size,
            offset=offset,
            sort_order=sort_order,
        )

        try:
            result = await opensearch_client.search(
                index=get_index_name(),
                body=agg_body,
            )
        except Exception as e:
            logger.error("Failed to list files by chunk_count (v2)", error=str(e))
            from utils.opensearch_utils import is_opensearch_auth_error

            if is_opensearch_auth_error(e):
                raise
            return {
                "files": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "after_key": None,
            }

        files = self._parse_terms_buckets(result, offset=offset)

        return {
            "files": files,
            "total": total,
            "is_approximate": is_approximate,
            "page": page,
            "page_size": page_size,
            "after_key": None,  # offset pagination; no cursor
        }

    async def search_files(
        self,
        user_id: str,
        jwt_token: str = None,
        query: str = "",
        page: int = 1,
        page_size: int = 25,
        connector_type: list[str] | None = None,
        mimetype: list[str] | None = None,
        owner: list[str] | None = None,
        after_key: dict | None = None,
        data_sources: list[str] | None = None,
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
            data_sources=data_sources,
        )

    def _build_filter_query(
        self,
        user_id: str,
        connector_type: list[str] | None = None,
        mimetype: list[str] | None = None,
        owner: list[str] | None = None,
        search: str | None = None,
        data_sources: list[str] | None = None,
    ) -> dict[str, Any]:
        def _effective_values(values: str | list[str] | None) -> list[str]:
            if values is None:
                return []
            if isinstance(values, str):
                values = [values]
            return [value for value in values if value != "*"]

        must = []
        filter_clauses = []

        effective_connector_types = _effective_values(connector_type)
        if effective_connector_types:
            clause = (
                {"term": {"connector_type": effective_connector_types[0]}}
                if len(effective_connector_types) == 1
                else {"terms": {"connector_type": effective_connector_types}}
            )
            filter_clauses.append(clause)

        effective_mimetypes = _effective_values(mimetype)
        if effective_mimetypes:
            clause = (
                {"term": {"mimetype": effective_mimetypes[0]}}
                if len(effective_mimetypes) == 1
                else {"terms": {"mimetype": effective_mimetypes}}
            )
            filter_clauses.append(clause)

        effective_owners = _effective_values(owner)
        if effective_owners:
            clause = (
                {"term": {"owner": effective_owners[0]}}
                if len(effective_owners) == 1
                else {"terms": {"owner": effective_owners}}
            )
            filter_clauses.append(clause)

        effective_sources = _effective_values(data_sources)
        if effective_sources:
            clause = (
                {"term": {"filename": effective_sources[0]}}
                if len(effective_sources) == 1
                else {"terms": {"filename": effective_sources}}
            )
            filter_clauses.append(clause)

        if search:
            must.append(
                {
                    "bool": {
                        "should": [
                            {
                                "wildcard": {
                                    "filename": {
                                        "value": f"*{search.lower()}*",
                                        "case_insensitive": True,
                                    }
                                }
                            },
                            {
                                "prefix": {
                                    "filename": {"value": search.lower(), "case_insensitive": True}
                                }
                            },
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
                            "missing_bucket": True,
                        }
                    }
                },
                *(
                    [
                        {
                            "filename_tiebreak": {
                                "terms": {
                                    "field": "filename",
                                    "order": sort_order,
                                    "missing_bucket": True,
                                }
                            }
                        }
                    ]
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
                                    "embedding_provider",
                                    "embedding_space_id",
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

    def _build_terms_aggregation_for_chunk_count(
        self,
        query: dict[str, Any],
        page_size: int,
        offset: int,
        sort_order: str,
    ) -> dict[str, Any]:
        """
        Build a terms aggregation sorted by chunk_count sub-agg.

        Terms agg supports `order: { sub_agg: asc/desc }`.  To implement
        offset-based pagination we request (offset + page_size) buckets and
        slice in Python — OpenSearch has no native offset for aggs.
        """
        return {
            "size": 0,
            "query": query,
            "aggs": {
                "files": {
                    "terms": {
                        "field": "filename",
                        "size": offset + page_size,
                        "order": {"chunk_count": sort_order},
                    },
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
                                    "embedding_provider",
                                    "embedding_space_id",
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

    def _parse_terms_buckets(self, result: dict[str, Any], offset: int = 0) -> list[dict[str, Any]]:
        """Parse terms agg buckets, applying offset slice. Returns files list."""
        buckets = result.get("aggregations", {}).get("files", {}).get("buckets", [])
        buckets = buckets[offset:]
        return self._buckets_to_files(buckets)

    async def _get_file_count(
        self, opensearch_client: Any, query: dict[str, Any]
    ) -> tuple[int, bool]:
        """Approximate unique-filename count via cardinality aggregation (O(1)).

        Returns (count, is_approximate).  is_approximate is always True on
        success (cardinality agg is inherently approximate) and True when the
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
            logger.warning(
                "Failed to retrieve file count; pagination total will show 0", error=str(e)
            )
            return 0, True

    def _parse_composite_buckets(
        self, result: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict | None]:
        """Parse composite agg buckets. Returns (files, next_after_key)."""
        agg = result.get("aggregations", {}).get("files", {})
        buckets = agg.get("buckets", [])
        next_after_key = agg.get("after_key")
        return self._buckets_to_files(buckets), next_after_key

    def _buckets_to_files(self, buckets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert raw aggregation buckets (composite or terms) to file dicts."""
        files = []
        for bucket in buckets:
            hits = bucket.get("file_metadata", {}).get("hits", {}).get("hits", [])
            if not hits:
                continue
            source = hits[0].get("_source", {})
            files.append(
                {
                    "filename": source.get("filename")
                    or (
                        bucket["key"].get("filename", "")
                        if isinstance(bucket["key"], dict)
                        else bucket.get("key", "")
                    ),
                    "document_id": source.get("document_id", ""),
                    "mimetype": source.get("mimetype", ""),
                    "file_size": source.get("file_size", 0),
                    "source_url": source.get("source_url", ""),
                    "owner": source.get("owner", ""),
                    "owner_name": source.get("owner_name", ""),
                    "owner_email": source.get("owner_email", ""),
                    "connector_type": source.get("connector_type", ""),
                    "embedding_model": source.get("embedding_model", ""),
                    "embedding_provider": source.get("embedding_provider", ""),
                    "embedding_space_id": source.get("embedding_space_id", ""),
                    "embedding_dimensions": source.get("embedding_dimensions"),
                    "indexed_time": source.get("indexed_time", ""),
                    "chunk_count": bucket.get("chunk_count", {}).get("value", 0),
                    "allowed_users": source.get("allowed_users", []),
                    "allowed_groups": source.get("allowed_groups", []),
                    "allowed_principal_labels": source.get("allowed_principal_labels", []),
                }
            )
        return files
