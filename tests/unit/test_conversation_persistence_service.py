import pytest

from services.conversation_persistence_service import (
    ConversationPersistenceService,
    CONVERSATION_METADATA_INDEX_NAME,
)
from config.settings import clients


class FakeOpenSearch:
    def __init__(self):
        self.docs = {}

    async def index(self, index, id, body, refresh=True):
        self.docs[(index, id)] = body

    async def search(self, index, body):
        user_id = body["query"]["term"]["user_id"]
        hits = []
        for (idx, _doc_id), source in self.docs.items():
            if idx == index and source.get("user_id") == user_id:
                hits.append({"_source": source})
        return {"hits": {"hits": hits}}

    async def get(self, index, id):
        return {"_source": self.docs[(index, id)]}

    async def delete(self, index, id, refresh=True):
        self.docs.pop((index, id), None)


@pytest.mark.asyncio
async def test_store_and_fetch_user_conversations_from_opensearch():
    service = ConversationPersistenceService()
    original = clients.opensearch
    clients.opensearch = FakeOpenSearch()
    try:
        await service.store_conversation_thread(
            "user-1",
            "resp-1",
            {
                "title": "Hello",
                "endpoint": "chat",
                "created_at": "2026-01-01T00:00:00",
                "last_activity": "2026-01-01T00:00:00",
                "total_messages": 2,
            },
        )

        conversations = await service.get_user_conversations("user-1")
        assert "resp-1" in conversations
        assert conversations["resp-1"]["title"] == "Hello"
        assert (CONVERSATION_METADATA_INDEX_NAME, "user-1:resp-1") in clients.opensearch.docs
    finally:
        clients.opensearch = original


@pytest.mark.asyncio
async def test_fallback_data_used_when_opensearch_unavailable():
    service = ConversationPersistenceService()
    original = clients.opensearch
    clients.opensearch = None
    try:
        await service.store_conversation_thread(
            "user-2",
            "resp-2",
            {
                "title": "Fallback",
                "endpoint": "chat",
                "total_messages": 1,
            },
        )
        conversations = await service.get_user_conversations("user-2")
        assert conversations["resp-2"]["title"] == "Fallback"
    finally:
        clients.opensearch = original
