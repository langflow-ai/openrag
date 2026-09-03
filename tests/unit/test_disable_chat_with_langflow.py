import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.chat_service import ChatService  # noqa: E402


@pytest.mark.asyncio
async def test_langflow_chat_uses_direct_chat_when_disabled(monkeypatch):
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", "true")
    monkeypatch.setattr(
        "config.settings.clients.ensure_langflow_client",
        AsyncMock(side_effect=AssertionError("Langflow should not be used")),
    )

    service = ChatService()
    service.chat = AsyncMock(return_value={"response": "ok", "response_id": "direct-id"})

    result = await service.langflow_chat(
        prompt="hello",
        user_id="oauth-user",
        jwt_token="jwt-token",
        previous_response_id="previous-id",
        stream=False,
        filter_id="filter-id",
        storage_user_id="db-user",
    )

    assert result == {"response": "ok", "response_id": "direct-id"}
    service.chat.assert_awaited_once_with(
        "hello",
        "oauth-user",
        "jwt-token",
        previous_response_id="previous-id",
        stream=False,
        filter_id="filter-id",
        storage_user_id="db-user",
    )


@pytest.mark.asyncio
async def test_langflow_history_uses_direct_history_when_disabled(monkeypatch):
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", "true")

    service = ChatService()
    service.get_chat_history = AsyncMock(
        return_value={
            "user_id": "db-user",
            "endpoint": "chat",
            "conversations": [],
            "total_conversations": 0,
        }
    )

    result = await service.get_langflow_history("db-user")

    assert result["endpoint"] == "chat"
    service.get_chat_history.assert_awaited_once_with("db-user")


@pytest.mark.asyncio
async def test_nudges_use_direct_generation_when_disabled(monkeypatch):
    """The one flag covers nudges too, not just chat and history.

    Without this, a deployment running without Langflow gets a chat page whose
    suggestion buttons 500 on every request.
    """
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", "true")
    monkeypatch.setattr(
        "config.settings.clients.ensure_langflow_client",
        AsyncMock(side_effect=AssertionError("Langflow should not be used")),
    )
    monkeypatch.setattr(
        "services.nudges_service.chat_completions",
        AsyncMock(return_value={"choices": [{"message": {"content": "Alpha\nBeta\nGamma"}}]}),
    )

    class _Search:
        async def search(self, query, **kwargs):
            return {"results": [{"text": "some corpus text"}]}

    service = ChatService(search_service=_Search())

    result = await service.langflow_nudges_chat(user_id="oauth-user", jwt_token="jwt-token")

    assert result == {"response": "Alpha\nBeta\nGamma"}
