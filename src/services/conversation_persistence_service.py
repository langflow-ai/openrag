"""
Conversation Persistence Service
Persists chat conversation metadata in OpenSearch so it can be shared across backend instances.
"""

from datetime import datetime
from typing import Any, Dict

from config.settings import clients
from utils.logging_config import get_logger

logger = get_logger(__name__)


CONVERSATION_METADATA_INDEX_NAME = "chat_conversation_metadata"
CONVERSATION_METADATA_INDEX_BODY = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
    "mappings": {
        "properties": {
            "user_id": {"type": "keyword"},
            "response_id": {"type": "keyword"},
            "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "endpoint": {"type": "keyword"},
            "created_at": {"type": "date"},
            "last_activity": {"type": "date"},
            "previous_response_id": {"type": "keyword"},
            "filter_id": {"type": "keyword"},
            "total_messages": {"type": "integer"},
        }
    },
}


class ConversationPersistenceService:
    """Persists conversation metadata in OpenSearch with in-memory fallback."""

    def __init__(self):
        self._fallback_conversations: Dict[str, Dict[str, Any]] = {}

    def _get_document_id(self, user_id: str, response_id: str) -> str:
        return f"{user_id}:{response_id}"

    def _serialize_datetime(self, obj: Any) -> Any:
        """Recursively convert datetime objects to ISO strings for JSON serialization."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {key: self._serialize_datetime(value) for key, value in obj.items()}
        if isinstance(obj, list):
            return [self._serialize_datetime(item) for item in obj]
        return obj

    async def get_user_conversations(self, user_id: str) -> Dict[str, Any]:
        """Get all persisted metadata for a user keyed by response_id."""
        if not user_id:
            return {}

        try:
            if not clients.opensearch:
                return self._fallback_conversations.get(user_id, {})

            result = await clients.opensearch.search(
                index=CONVERSATION_METADATA_INDEX_NAME,
                body={
                    "query": {"term": {"user_id": user_id}},
                    "size": 1000,
                    "sort": [{"last_activity": {"order": "desc", "unmapped_type": "date"}}],
                },
            )

            conversations: Dict[str, Any] = {}
            for hit in result.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                response_id = source.get("response_id")
                if response_id:
                    metadata = dict(source)
                    metadata.pop("user_id", None)
                    conversations[response_id] = metadata

            self._fallback_conversations[user_id] = conversations
            return conversations
        except Exception as e:
            logger.warning(
                "Failed to load conversation metadata from OpenSearch, using fallback",
                user_id=user_id,
                error=str(e),
            )
            return self._fallback_conversations.get(user_id, {})

    async def store_conversation_thread(
        self, user_id: str, response_id: str, conversation_state: Dict[str, Any]
    ):
        """Store conversation metadata in OpenSearch."""
        if user_id not in self._fallback_conversations:
            self._fallback_conversations[user_id] = {}

        serialized = self._serialize_datetime(conversation_state)
        serialized["user_id"] = user_id
        serialized["response_id"] = response_id

        self._fallback_conversations[user_id][response_id] = {
            key: value for key, value in serialized.items() if key != "user_id"
        }

        try:
            if not clients.opensearch:
                return

            await clients.opensearch.index(
                index=CONVERSATION_METADATA_INDEX_NAME,
                id=self._get_document_id(user_id, response_id),
                body=serialized,
                refresh=True,
            )
        except Exception as e:
            logger.warning(
                "Failed to persist conversation metadata to OpenSearch",
                user_id=user_id,
                response_id=response_id,
                error=str(e),
            )

    async def get_conversation_thread(self, user_id: str, response_id: str) -> Dict[str, Any]:
        """Get a specific conversation metadata record."""
        try:
            if not clients.opensearch:
                return self._fallback_conversations.get(user_id, {}).get(response_id, {})

            result = await clients.opensearch.get(
                index=CONVERSATION_METADATA_INDEX_NAME,
                id=self._get_document_id(user_id, response_id),
            )
            source = result.get("_source", {})
            source.pop("user_id", None)
            return source
        except Exception:
            return self._fallback_conversations.get(user_id, {}).get(response_id, {})

    async def delete_conversation_thread(self, user_id: str, response_id: str) -> bool:
        """Delete a specific conversation metadata record."""
        deleted = False

        if user_id in self._fallback_conversations and response_id in self._fallback_conversations[user_id]:
            del self._fallback_conversations[user_id][response_id]
            deleted = True

        try:
            if not clients.opensearch:
                return deleted

            await clients.opensearch.delete(
                index=CONVERSATION_METADATA_INDEX_NAME,
                id=self._get_document_id(user_id, response_id),
                refresh=True,
            )
            return True
        except Exception as e:
            logger.debug(
                "Failed to delete conversation metadata from OpenSearch",
                user_id=user_id,
                response_id=response_id,
                error=str(e),
            )
            return deleted

    async def clear_user_conversations(self, user_id: str):
        """Clear all conversation metadata for a user."""
        self._fallback_conversations.pop(user_id, None)

        try:
            if not clients.opensearch:
                return

            await clients.opensearch.delete_by_query(
                index=CONVERSATION_METADATA_INDEX_NAME,
                body={"query": {"term": {"user_id": user_id}}},
                refresh=True,
            )
        except Exception as e:
            logger.warning(
                "Failed to clear conversation metadata for user",
                user_id=user_id,
                error=str(e),
            )

    async def get_storage_stats(self) -> Dict[str, Any]:
        """Get basic storage statistics for conversation metadata."""
        fallback_total = sum(len(v) for v in self._fallback_conversations.values())

        try:
            if not clients.opensearch:
                return {
                    "total_users": len(self._fallback_conversations),
                    "total_conversations": fallback_total,
                    "index": CONVERSATION_METADATA_INDEX_NAME,
                    "opensearch_available": False,
                }

            count_response = await clients.opensearch.count(
                index=CONVERSATION_METADATA_INDEX_NAME,
                body={"query": {"match_all": {}}},
            )
            return {
                "total_users": len(self._fallback_conversations),
                "total_conversations": count_response.get("count", 0),
                "index": CONVERSATION_METADATA_INDEX_NAME,
                "opensearch_available": True,
            }
        except Exception as e:
            logger.warning("Failed to get OpenSearch storage stats", error=str(e))
            return {
                "total_users": len(self._fallback_conversations),
                "total_conversations": fallback_total,
                "index": CONVERSATION_METADATA_INDEX_NAME,
                "opensearch_available": False,
            }


# Global instance
conversation_persistence = ConversationPersistenceService()
