import json
from datetime import datetime
from typing import Any, Dict, Optional

from utils.logging_config import get_logger

KNOWLEDGE_FILTERS_INDEX_NAME = "knowledge_filters"

logger = get_logger(__name__)


def _serialize_normalized_query_data(data: dict) -> str:
    """Align with ``normalize_query_data`` in api/knowledge_filter.py."""
    filters = data.get("filters") or {}
    normalized_filters = {
        "data_sources": filters.get("data_sources", ["*"]),
        "data_source_refs": filters.get("data_source_refs", []),
        "document_types": filters.get("document_types", ["*"]),
        "owners": filters.get("owners", ["*"]),
        "connector_types": filters.get("connector_types", ["*"]),
    }
    normalized = {
        "query": data.get("query", ""),
        "filters": normalized_filters,
        "limit": data.get("limit", 10),
        "scoreThreshold": data.get("scoreThreshold", 0),
        "color": data.get("color", "zinc"),
        "icon": data.get("icon", "filter"),
    }
    return json.dumps(normalized)


class KnowledgeFilterService:
    def __init__(self, session_manager=None):
        self.session_manager = session_manager

    async def _enrich_filter_doc_query_data(
        self,
        filter_doc: Dict[str, Any],
        user_id: str | None = None,
        jwt_token: str | None = None,
    ) -> Dict[str, Any]:
        """Enrich ``query_data.filters.data_source_refs`` before persistence."""
        query_data = filter_doc.get("query_data")
        if not query_data:
            return filter_doc
        if not isinstance(query_data, str):
            query_data = _serialize_normalized_query_data(query_data)
        enriched_query_data = await self.enrich_data_source_refs_in_query_data(
            query_data,
            user_id=user_id,
            jwt_token=jwt_token,
        )
        enriched_filter_doc = dict(filter_doc)
        enriched_filter_doc["query_data"] = enriched_query_data
        return enriched_filter_doc

    async def create_knowledge_filter(
        self, filter_doc: Dict[str, Any], user_id: str = None, jwt_token: str = None
    ) -> Dict[str, Any]:
        """Create a new knowledge filter"""
        try:
            filter_doc = await self._enrich_filter_doc_query_data(
                filter_doc, user_id=user_id, jwt_token=jwt_token
            )
            # Get user's OpenSearch client with JWT for OIDC auth
            opensearch_client = self.session_manager.get_user_opensearch_client(
                user_id, jwt_token
            )

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
            logger.exception("create_knowledge_filter failed", error=str(e))
            return {"success": False, "error": "Failed to create knowledge filter"}

    async def upsert_knowledge_filter(
        self, filter_doc: Dict[str, Any], user_id: str = None, jwt_token: str = None
    ) -> Dict[str, Any]:
        """Create or replace a knowledge filter atomically by id."""
        try:
            filter_doc = await self._enrich_filter_doc_query_data(
                filter_doc, user_id=user_id, jwt_token=jwt_token
            )
            opensearch_client = self.session_manager.get_user_opensearch_client(
                user_id, jwt_token
            )
            result = await opensearch_client.index(
                index=KNOWLEDGE_FILTERS_INDEX_NAME,
                id=filter_doc["id"],
                body=filter_doc,
                refresh="wait_for",
            )
            if result.get("result") in ["created", "updated"]:
                try:
                    await opensearch_client.indices.refresh(
                        index=KNOWLEDGE_FILTERS_INDEX_NAME
                    )
                except Exception:
                    pass
                return {"success": True, "id": filter_doc["id"], "filter": filter_doc}
            return {"success": False, "error": "Failed to upsert knowledge filter"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def search_knowledge_filters(
        self, query: str, user_id: str = None, jwt_token: str = None, limit: int = 20
    ) -> Dict[str, Any]:
        """Search for knowledge filters by name, description, or query content"""
        try:
            # Get user's OpenSearch client with JWT for OIDC auth
            opensearch_client = self.session_manager.get_user_opensearch_client(
                user_id, jwt_token
            )

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

            return {"success": True, "filters": filters}

        except Exception as e:
            logger.exception("search_knowledge_filters failed", error=str(e))
            return {
                "success": False,
                "error": "Failed to search knowledge filters",
                "filters": [],
            }

    async def get_knowledge_filter(
        self, filter_id: str, user_id: str = None, jwt_token: str = None
    ) -> Dict[str, Any]:
        """Get a specific knowledge filter by ID"""
        try:
            # Get user's OpenSearch client with JWT for OIDC auth
            opensearch_client = self.session_manager.get_user_opensearch_client(
                user_id, jwt_token
            )

            result = await opensearch_client.get(
                index=KNOWLEDGE_FILTERS_INDEX_NAME, id=filter_id
            )

            if result.get("found"):
                knowledge_filter = result["_source"]
                return {"success": True, "filter": knowledge_filter}
            else:
                return {"success": False, "error": "Knowledge filter not found"}

        except Exception as e:
            logger.exception("get_knowledge_filter failed", error=str(e))
            return {"success": False, "error": "Failed to get knowledge filter"}

    async def update_knowledge_filter(
        self,
        filter_id: str,
        updates: Dict[str, Any],
        user_id: str = None,
        jwt_token: str = None,
    ) -> Dict[str, Any]:
        """Update an existing knowledge filter"""
        try:
            if "query_data" in updates:
                query_data = updates.get("query_data")
                if query_data:
                    if not isinstance(query_data, str):
                        query_data = _serialize_normalized_query_data(query_data)
                    updates = dict(updates)
                    updates["query_data"] = await self.enrich_data_source_refs_in_query_data(
                        query_data,
                        user_id=user_id,
                        jwt_token=jwt_token,
                    )
            # Get user's OpenSearch client with JWT for OIDC auth
            opensearch_client = self.session_manager.get_user_opensearch_client(
                user_id, jwt_token
            )

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
                updated_doc = await opensearch_client.get(
                    index=KNOWLEDGE_FILTERS_INDEX_NAME, id=filter_id
                )
                return {"success": True, "filter": updated_doc["_source"]}
            else:
                return {"success": False, "error": "Failed to update knowledge filter"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _sample_document_id_for_filename(
        self,
        filename: str,
        user_id: str | None,
        jwt_token: str | None,
    ) -> str | None:
        """Return a document_id from one chunk with this filename, if any."""
        from config.settings import get_index_name
        from utils.opensearch_queries import build_filename_search_body

        fn = (filename or "").strip()
        if not fn:
            return None
        try:
            opensearch_client = self.session_manager.get_user_opensearch_client(
                user_id, jwt_token
            )
            body = build_filename_search_body(
                fn, size=5, source=["document_id"]
            )
            resp = await opensearch_client.search(
                index=get_index_name(), body=body
            )
            for h in resp.get("hits", {}).get("hits", []):
                src = h.get("_source") or {}
                did = src.get("document_id")
                if did is not None and str(did).strip():
                    return str(did).strip()
        except Exception as e:
            logger.warning(
                "Could not resolve document_id for filename",
                filename=fn,
                error=str(e),
            )
        return None

    async def enrich_data_source_refs_in_query_data(
        self,
        query_data_str: str,
        user_id: str | None = None,
        jwt_token: str | None = None,
    ) -> str:
        """Fill missing ``document_id`` on refs using the corpus index."""
        try:
            data = json.loads(query_data_str)
        except json.JSONDecodeError:
            return query_data_str
        filters = data.get("filters") or {}
        refs = filters.get("data_source_refs")
        if not refs or not isinstance(refs, list):
            return query_data_str
        changed = False
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            if (ref.get("document_id") or "").strip():
                continue
            fn = (ref.get("filename") or "").strip()
            if not fn:
                continue
            sampled = await self._sample_document_id_for_filename(
                fn, user_id, jwt_token
            )
            if sampled:
                ref["document_id"] = sampled
                changed = True
        if not changed:
            return query_data_str
        filters["data_source_refs"] = refs
        data["filters"] = filters
        return _serialize_normalized_query_data(data)

    async def sync_filters_after_document_rename(
        self,
        old_filename: str,
        new_filename: str,
        document_id: str | None,
        user_id: str | None = None,
        jwt_token: str | None = None,
    ) -> Dict[str, Any]:
        """
        Patch saved filters when a file is renamed: update ``data_source_refs``
        filenames and multiselect ``data_sources`` values so searches still match.
        """
        from pathlib import Path

        from utils.file_utils import get_filename_aliases

        old = (old_filename or "").strip()
        new = (new_filename or "").strip()
        did = (document_id or "").strip() or None
        if not old or not new:
            return {"success": True, "updated_filters": 0}

        match_keys: set[str] = set(get_filename_aliases(old))
        if old:
            match_keys.add(old)
        # Labels often omit extension or differ by stem only (e.g. task_report vs task_report.pdf).
        expanded: set[str] = set()
        for k in match_keys:
            if not k:
                continue
            expanded.add(k)
            expanded.add(Path(k).stem)
            expanded.add(Path(k).name)
        match_keys = {x for x in expanded if x}

        try:
            listed = await self.search_knowledge_filters(
                "", user_id=user_id, jwt_token=jwt_token, limit=1000
            )
            if not listed.get("success"):
                return listed
            updated_count = 0
            for fdoc in listed.get("filters") or []:
                qraw = fdoc.get("query_data")
                if not qraw:
                    continue
                try:
                    data = json.loads(qraw) if isinstance(qraw, str) else (qraw or {})
                except json.JSONDecodeError:
                    continue
                filters_part = data.get("filters") or {}
                changed = False

                ds = list(filters_part.get("data_sources") or [])
                if ds and "*" not in ds:
                    new_ds = []
                    for v in ds:
                        vs = str(v).strip()
                        if vs in match_keys:
                            new_ds.append(did if did else new)
                            changed = True
                        else:
                            new_ds.append(v)
                    new_ds = list(dict.fromkeys(new_ds))
                    filters_part["data_sources"] = new_ds

                refs = filters_part.get("data_source_refs")
                if isinstance(refs, list) and len(refs) > 0:
                    new_refs = []
                    for ref in refs:
                        if not isinstance(ref, dict):
                            new_refs.append(ref)
                            continue
                        rfn = (ref.get("filename") or "").strip()
                        rdoc = (ref.get("document_id") or "").strip() or None
                        new_ref = dict(ref)
                        if did and rdoc == did:
                            if rfn != new:
                                new_ref["filename"] = new
                                changed = True
                        elif rfn in match_keys:
                            new_ref["filename"] = new
                            if did and not rdoc:
                                new_ref["document_id"] = did
                            changed = True
                        new_refs.append(new_ref)
                    filters_part["data_source_refs"] = new_refs

                if not changed:
                    continue

                data["filters"] = filters_part
                updated_q = _serialize_normalized_query_data(data)
                fid = fdoc.get("id")
                if not fid:
                    continue
                up = await self.update_knowledge_filter(
                    str(fid),
                    {
                        "query_data": updated_q,
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                    user_id=user_id,
                    jwt_token=jwt_token,
                )
                if up.get("success"):
                    updated_count += 1

            if updated_count:
                logger.info(
                    "Synced knowledge filters after document rename",
                    updated_filters=updated_count,
                    old_filename=old,
                    new_filename=new,
                    user_id=user_id,
                )
            return {"success": True, "updated_filters": updated_count}
        except Exception as e:
            logger.exception(
                "sync_filters_after_document_rename failed",
                error=str(e),
                old_filename=old,
                user_id=user_id,
            )
            return {
                "success": False,
                "error": "Failed to sync knowledge filters after document rename",
                "updated_filters": 0,
            }

    async def delete_knowledge_filter(
        self, filter_id: str, user_id: str = None, jwt_token: str = None
    ) -> Dict[str, Any]:
        """Delete a knowledge filter"""
        try:
            # Get user's OpenSearch client with JWT for OIDC auth
            opensearch_client = self.session_manager.get_user_opensearch_client(
                user_id, jwt_token
            )

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
            error_str = str(e)
            if "not_found" in error_str or "NotFoundError" in error_str:
                return {
                    "success": False,
                    "error": "Knowledge filter not found or already deleted",
                }
            elif "AuthenticationException" in error_str:
                return {
                    "success": False,
                    "error": "Access denied: insufficient permissions",
                }
            else:
                return {
                    "success": False,
                    "error": f"Delete operation failed: {error_str}",
                }

    async def add_subscription(
        self,
        filter_id: str,
        subscription_data: Dict[str, Any],
        user_id: str = None,
        jwt_token: str = None,
    ) -> Dict[str, Any]:
        """Add a subscription to a knowledge filter"""
        try:
            opensearch_client = self.session_manager.get_user_opensearch_client(
                user_id, jwt_token
            )

            # Get the current filter document
            filter_result = await self.get_knowledge_filter(
                filter_id, user_id, jwt_token
            )
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
                    "updated_at": subscription_data[
                        "created_at"
                    ],  # Use the same timestamp
                }
            }

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
    ) -> Dict[str, Any]:
        """Remove a subscription from a knowledge filter"""
        try:
            opensearch_client = self.session_manager.get_user_opensearch_client(
                user_id, jwt_token
            )

            # Get the current filter document
            filter_result = await self.get_knowledge_filter(
                filter_id, user_id, jwt_token
            )
            if not filter_result.get("success"):
                return filter_result

            filter_doc = filter_result["filter"]

            # Remove subscription from the subscriptions array
            subscriptions = filter_doc.get("subscriptions", [])
            updated_subscriptions = [
                sub
                for sub in subscriptions
                if sub.get("subscription_id") != subscription_id
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
    ) -> Dict[str, Any]:
        """Get all subscriptions for a knowledge filter"""
        try:
            filter_result = await self.get_knowledge_filter(
                filter_id, user_id, jwt_token
            )
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
