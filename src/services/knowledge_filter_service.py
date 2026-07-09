from typing import Any

KNOWLEDGE_FILTERS_INDEX_NAME = "knowledge_filters"


class KnowledgeFilterService:
    def __init__(self, session_manager=None):
        self.session_manager = session_manager

    def _user_client(self, user_id: str = None, jwt_token: str = None):
        return self.session_manager.get_user_opensearch_client(user_id, jwt_token)

    def _write_client(self, user_id: str = None, jwt_token: str = None):
        # OpenSearch rejects write requests on indices protected by filter-level
        # DLS. The app enforces ownership/visibility with the scoped client, then
        # performs trusted writes with the admin client.
        from config.settings import clients

        if clients.opensearch is None:
            raise RuntimeError("Backend OpenSearch write client is unavailable")
        return clients.opensearch

    async def _attach_active_source_counts(self, filters: list[dict[str, Any]]) -> None:
        """Annotate each filter with active_source_count (mutates filters in place).

        Counts how many of each filter's configured data sources still have indexed
        documents, via a single batched terms aggregation against the documents index
        using the admin client (so the count is the same for every viewer of a shared
        filter, not DLS-scoped per user). Filters scoped to "*" are skipped.
        """
        try:
            import json

            from config.settings import clients, get_index_name
            from utils.logging_config import get_logger
            from utils.opensearch_queries import build_existing_filenames_agg_body

            data_sources_by_filter: list[list[str] | None] = []
            all_filenames = set()
            for knowledge_filter in filters:
                try:
                    data_sources = (
                        json.loads(knowledge_filter.get("query_data") or "{}")
                        .get("filters", {})
                        .get("data_sources")
                    )
                except Exception:
                    data_sources_by_filter.append(None)
                    continue

                if not data_sources or data_sources == ["*"]:
                    data_sources_by_filter.append(None)
                    continue
                data_sources_by_filter.append(data_sources)
                all_filenames.update(data_sources)

            if not all_filenames or clients.opensearch is None:
                return

            existence_result = await clients.opensearch.search(
                index=get_index_name(),
                body=build_existing_filenames_agg_body(list(all_filenames)),
            )
            existing_filenames = {
                bucket["key"] for bucket in existence_result["aggregations"]["filenames"]["buckets"]
            }

            for knowledge_filter, data_sources in zip(filters, data_sources_by_filter, strict=True):
                if data_sources:
                    knowledge_filter["active_source_count"] = sum(
                        1 for source in data_sources if source in existing_filenames
                    )
        except Exception:
            get_logger(__name__).warning("active_source_count computation failed", exc_info=True)

    async def create_knowledge_filter(
        self, filter_doc: dict[str, Any], user_id: str = None, jwt_token: str = None
    ) -> dict[str, Any]:
        """Create a new knowledge filter"""
        try:
            opensearch_client = self._write_client(user_id, jwt_token)

            # Index the knowledge filter document
            result = await opensearch_client.index(
                index=KNOWLEDGE_FILTERS_INDEX_NAME,
                id=filter_doc["id"],
                body=filter_doc,
                refresh="wait_for",
            )

            if result.get("result") == "created":
                # Extra safety: ensure visibility in subsequent searches
                try:
                    await opensearch_client.indices.refresh(index=KNOWLEDGE_FILTERS_INDEX_NAME)
                except Exception:
                    pass
                return {"success": True, "id": filter_doc["id"], "filter": filter_doc}
            else:
                return {"success": False, "error": "Failed to create knowledge filter"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def search_knowledge_filters(
        self, query: str, user_id: str = None, jwt_token: str = None, limit: int = 20
    ) -> dict[str, Any]:
        """Search for knowledge filters by name, description, or query content"""
        try:
            opensearch_client = self._user_client(user_id, jwt_token)

            if query.strip():
                # Search across name, description, and query_data fields
                search_body = {
                    "query": {
                        "multi_match": {
                            "query": query,
                            "fields": ["name^3", "description^2", "query_data"],
                            "type": "best_fields",
                            "fuzziness": "AUTO",
                        }
                    },
                    "sort": [
                        {"_score": {"order": "desc"}},
                        {"updated_at": {"order": "desc"}},
                    ],
                    "_source": [
                        "id",
                        "name",
                        "description",
                        "query_data",
                        "owner",
                        "created_at",
                        "updated_at",
                    ],
                    "size": limit,
                }
            else:
                # No query - return all knowledge filters sorted by most recent
                search_body = {
                    "query": {"match_all": {}},
                    "sort": [{"updated_at": {"order": "desc"}}],
                    "_source": [
                        "id",
                        "name",
                        "description",
                        "query_data",
                        "owner",
                        "created_at",
                        "updated_at",
                    ],
                    "size": limit,
                }

            result = await opensearch_client.search(
                index=KNOWLEDGE_FILTERS_INDEX_NAME, body=search_body
            )

            # Transform results
            filters = []
            for hit in result["hits"]["hits"]:
                knowledge_filter = hit["_source"]
                knowledge_filter["score"] = hit.get("_score")
                filters.append(knowledge_filter)

            await self._attach_active_source_counts(filters)

            return {"success": True, "filters": filters}

        except Exception as e:
            return {"success": False, "error": str(e), "filters": []}

    async def get_knowledge_filter(
        self, filter_id: str, user_id: str = None, jwt_token: str = None
    ) -> dict[str, Any]:
        """Get a specific knowledge filter by ID"""
        try:
            opensearch_client = self._user_client(user_id, jwt_token)

            result = await opensearch_client.get(index=KNOWLEDGE_FILTERS_INDEX_NAME, id=filter_id)

            if result.get("found"):
                knowledge_filter = result["_source"]
                return {"success": True, "filter": knowledge_filter}
            else:
                return {"success": False, "error": "Knowledge filter not found"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def update_knowledge_filter(
        self,
        filter_id: str,
        updates: dict[str, Any],
        user_id: str = None,
        jwt_token: str = None,
    ) -> dict[str, Any]:
        """Update an existing knowledge filter"""
        try:
            existing = await self.get_knowledge_filter(filter_id, user_id, jwt_token)
            if not existing.get("success"):
                return existing

            opensearch_client = self._write_client(user_id, jwt_token)

            # Update the document
            result = await opensearch_client.update(
                index=KNOWLEDGE_FILTERS_INDEX_NAME,
                id=filter_id,
                body={"doc": updates},
                refresh="wait_for",
            )

            if result.get("result") in ["updated", "noop"]:
                # Get the updated document
                # Ensure visibility before fetching/returning
                try:
                    await opensearch_client.indices.refresh(index=KNOWLEDGE_FILTERS_INDEX_NAME)
                except Exception:
                    pass
                updated_doc = await self.get_knowledge_filter(filter_id, user_id, jwt_token)
                if updated_doc.get("success"):
                    return updated_doc
                return {"success": False, "error": "Failed to read updated knowledge filter"}
            else:
                return {"success": False, "error": "Failed to update knowledge filter"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def delete_knowledge_filter(
        self, filter_id: str, user_id: str = None, jwt_token: str = None
    ) -> dict[str, Any]:
        """Delete a knowledge filter"""
        try:
            existing = await self.get_knowledge_filter(filter_id, user_id, jwt_token)
            if not existing.get("success"):
                return {
                    "success": False,
                    "error": "Knowledge filter not found or access denied",
                }

            opensearch_client = self._write_client(user_id, jwt_token)

            result = await opensearch_client.delete(
                index=KNOWLEDGE_FILTERS_INDEX_NAME,
                id=filter_id,
                refresh="wait_for",
            )

            if result.get("result") == "deleted":
                # Extra safety: ensure visibility in subsequent searches
                try:
                    await opensearch_client.indices.refresh(index=KNOWLEDGE_FILTERS_INDEX_NAME)
                except Exception:
                    pass
                return {
                    "success": True,
                    "message": "Knowledge filter deleted successfully",
                }
            else:
                return {"success": False, "error": "Failed to delete knowledge filter"}

        except Exception as e:
            from utils.opensearch_utils import AUTH_ERROR_MESSAGE, is_opensearch_auth_error

            error_str = str(e)
            if "not_found" in error_str or "NotFoundError" in error_str:
                return {
                    "success": False,
                    "error": "Knowledge filter not found or already deleted",
                }
            elif is_opensearch_auth_error(error_str):
                return {
                    "success": False,
                    "error": AUTH_ERROR_MESSAGE,
                }
            else:
                return {
                    "success": False,
                    "error": f"Delete operation failed: {error_str}",
                }

    async def add_subscription(
        self,
        filter_id: str,
        subscription_data: dict[str, Any],
        user_id: str = None,
        jwt_token: str = None,
    ) -> dict[str, Any]:
        """Add a subscription to a knowledge filter"""
        try:
            # Get the current filter document
            filter_result = await self.get_knowledge_filter(filter_id, user_id, jwt_token)
            if not filter_result.get("success"):
                return filter_result

            filter_doc = filter_result["filter"]

            # Add subscription to the subscriptions array
            subscriptions = filter_doc.get("subscriptions", [])
            subscriptions.append(subscription_data)

            # Update the filter document
            update_body = {
                "doc": {
                    "subscriptions": subscriptions,
                    "updated_at": subscription_data["created_at"],  # Use the same timestamp
                }
            }

            opensearch_client = self._write_client(user_id, jwt_token)
            result = await opensearch_client.update(
                index=KNOWLEDGE_FILTERS_INDEX_NAME,
                id=filter_id,
                body=update_body,
                refresh="wait_for",
            )

            if result.get("result") in ["updated", "noop"]:
                return {"success": True, "subscription": subscription_data}
            else:
                return {"success": False, "error": "Failed to add subscription"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def remove_subscription(
        self,
        filter_id: str,
        subscription_id: str,
        user_id: str = None,
        jwt_token: str = None,
    ) -> dict[str, Any]:
        """Remove a subscription from a knowledge filter"""
        try:
            # Get the current filter document
            filter_result = await self.get_knowledge_filter(filter_id, user_id, jwt_token)
            if not filter_result.get("success"):
                return filter_result

            filter_doc = filter_result["filter"]

            # Remove subscription from the subscriptions array
            subscriptions = filter_doc.get("subscriptions", [])
            updated_subscriptions = [
                sub for sub in subscriptions if sub.get("subscription_id") != subscription_id
            ]

            if len(updated_subscriptions) == len(subscriptions):
                return {"success": False, "error": "Subscription not found"}

            # Update the filter document
            from datetime import datetime

            update_body = {
                "doc": {
                    "subscriptions": updated_subscriptions,
                    "updated_at": datetime.utcnow().isoformat(),
                }
            }

            opensearch_client = self._write_client(user_id, jwt_token)
            result = await opensearch_client.update(
                index=KNOWLEDGE_FILTERS_INDEX_NAME, id=filter_id, body=update_body
            )

            if result.get("result") in ["updated", "noop"]:
                return {"success": True, "message": "Subscription removed successfully"}
            else:
                return {"success": False, "error": "Failed to remove subscription"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_filter_subscriptions(
        self, filter_id: str, user_id: str = None, jwt_token: str = None
    ) -> dict[str, Any]:
        """Get all subscriptions for a knowledge filter"""
        try:
            filter_result = await self.get_knowledge_filter(filter_id, user_id, jwt_token)
            if not filter_result.get("success"):
                return filter_result

            filter_doc = filter_result["filter"]
            subscriptions = filter_doc.get("subscriptions", [])

            return {
                "success": True,
                "filter_id": filter_id,
                "filter_name": filter_doc.get("name"),
                "subscriptions": subscriptions,
            }

        except Exception as e:
            return {"success": False, "error": str(e), "subscriptions": []}
