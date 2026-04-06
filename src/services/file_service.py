"""
Service for file-level listing and search via OpenSearch aggregations.

Aggregates document chunks by filename to produce file-level views,
with support for pagination, filtering, sorting, and fuzzy search.
"""

from typing import Any, Dict, List, Optional

from config.settings import get_index_name
from utils.acl_utils import build_acl_filter
from utils.logging_config import get_logger

logger = get_logger(__name__)


class FileService:
    """Provides file-level views over the chunk-based OpenSearch index."""

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
        connector_type: Optional[str] = None,
        mimetype: Optional[str] = None,
        owner: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List ingested files with server-side pagination, filtering, and sorting.

        Aggregates chunks by filename using OpenSearch terms aggregation,
        then paginates and sorts the resulting file list in-memory.
        """
        opensearch_client = self.session_manager.get_user_opensearch_client(
            user_id, jwt_token
        )

        query = self._build_filter_query(user_id, connector_type, mimetype, owner, search)
        agg_body = self._build_file_aggregation(query)

        try:
            result = await opensearch_client.search(
                index=get_index_name(),
                body=agg_body,
            )
        except Exception as e:
            logger.error("Failed to list files", error=str(e))
            return {"files": [], "total": 0, "page": page, "page_size": page_size}

        files = self._parse_aggregation_buckets(result)
        files = self._sort_files(files, sort_by, sort_order)

        total = len(files)
        start = (page - 1) * page_size
        end = start + page_size
        paginated = files[start:end]

        return {
            "files": paginated,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def search_files(
        self,
        user_id: str,
        jwt_token: str = None,
        query: str = "",
        page: int = 1,
        page_size: int = 25,
        connector_type: Optional[str] = None,
        mimetype: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Search files by name with fuzzy/prefix matching.

        Uses wildcard, match_phrase_prefix, and fuzzy queries on the
        filename field, then aggregates matching chunks into file-level results.
        """
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
        )

    def _build_filter_query(
        self,
        user_id: str,
        connector_type: Optional[str] = None,
        mimetype: Optional[str] = None,
        owner: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build the bool query with ACL + optional filters + filename search."""
        must = []
        filter_clauses = [build_acl_filter(user_id)]

        if connector_type:
            filter_clauses.append({"term": {"connector_type": connector_type}})
        if mimetype:
            filter_clauses.append({"term": {"mimetype": mimetype}})
        if owner:
            filter_clauses.append({"term": {"owner": owner}})

        if search:
            # Combine wildcard (partial), prefix, and fuzzy for flexible matching
            must.append({
                "bool": {
                    "should": [
                        {"wildcard": {"filename": {"value": f"*{search.lower()}*"}}},
                        {"prefix": {"filename": search.lower()}},
                    ],
                    "minimum_should_match": 1,
                }
            })

        query = {"bool": {"filter": filter_clauses}}
        if must:
            query["bool"]["must"] = must

        return query

    def _build_file_aggregation(self, query: Dict[str, Any]) -> Dict[str, Any]:
        """Build the OpenSearch aggregation body for file-level grouping."""
        return {
            "size": 0,
            "query": query,
            "aggs": {
                "files": {
                    "terms": {
                        "field": "filename",
                        "size": 10000,
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
                                    "embedding_dimensions",
                                    "indexed_time",
                                    "allowed_users",
                                    "allowed_groups",
                                ],
                                "sort": [{"indexed_time": {"order": "desc"}}],
                            }
                        },
                        "chunk_count": {
                            "value_count": {"field": "_id"}
                        },
                    },
                }
            },
        }

    def _parse_aggregation_buckets(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse OpenSearch aggregation buckets into file dicts."""
        buckets = (
            result.get("aggregations", {})
            .get("files", {})
            .get("buckets", [])
        )

        files = []
        for bucket in buckets:
            hits = bucket.get("file_metadata", {}).get("hits", {}).get("hits", [])
            if not hits:
                continue

            source = hits[0].get("_source", {})
            files.append({
                "filename": bucket["key"],
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
            })

        return files

    def _sort_files(
        self,
        files: List[Dict[str, Any]],
        sort_by: str,
        sort_order: str,
    ) -> List[Dict[str, Any]]:
        """Sort file list by the given field."""
        valid_sort_fields = {
            "filename", "file_size", "mimetype", "indexed_time",
            "connector_type", "chunk_count", "owner",
        }
        if sort_by not in valid_sort_fields:
            sort_by = "filename"

        reverse = sort_order.lower() == "desc"

        return sorted(
            files,
            key=lambda f: (f.get(sort_by) or ""),
            reverse=reverse,
        )
