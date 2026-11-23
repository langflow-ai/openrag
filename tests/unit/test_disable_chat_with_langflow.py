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
    monkeypatch.setattr("services.chat_service.DISABLE_CHAT_WITH_LANGFLOW", True)
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
        owner_name=None,
        owner_email=None,
        can_upload_knowledge=False,
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
        owner_name=None,
        owner_email=None,
        can_upload_knowledge=False,
    )


@pytest.mark.asyncio
async def test_chat_history_uses_native_history():
    service = ChatService()
    service.native_chat_history_service.history = AsyncMock(
        return_value={
            "user_id": "db-user",
            "conversations": [],
            "total_conversations": 0,
        }
    )

    result = await service.get_chat_history("db-user")

    assert result["user_id"] == "db-user"
    service.native_chat_history_service.history.assert_awaited_once_with("db-user")


@pytest.mark.asyncio
async def test_langflow_chat_resumes_an_owned_native_conversation_when_disabled(monkeypatch):
    monkeypatch.setattr("services.chat_service.DISABLE_CHAT_WITH_LANGFLOW", True)
    service = ChatService()
    service.native_chat_history_service.owns_conversation = AsyncMock(return_value=True)
    service.chat = AsyncMock(return_value={"response": "ok", "response_id": "native-id"})

    await service.langflow_chat(
        prompt="hello",
        user_id="oauth-user",
        jwt_token="jwt-token",
        conversation_id="native-id",
        stream=False,
        storage_user_id="db-user",
    )

    service.native_chat_history_service.owns_conversation.assert_awaited_once_with(
        "native-id", "db-user"
    )
    assert service.chat.await_args.kwargs["previous_response_id"] == "native-id"


@pytest.mark.asyncio
async def test_delete_all_sessions_deletes_native_and_langflow_history(monkeypatch):
    monkeypatch.setattr("services.chat_service.DISABLE_CHAT_WITH_LANGFLOW", True)
    service = ChatService()
    service.native_chat_history_service.conversation_ids = AsyncMock(
        return_value=["native-1", "native-2"]
    )
    service.native_chat_history_service.delete_all = AsyncMock(return_value=2)
    service.session_ownership_service.release_conversation_sessions = AsyncMock()
    service.delete_session = AsyncMock(return_value={"success": True})

    async def get_user_conversations(_user_id):
        return {"langflow-1": {}, "langflow-2": {}}

    monkeypatch.setattr("agent.get_user_conversations", get_user_conversations)

    result = await service.delete_all_user_sessions("db-user")

    assert result == {
        "success": True,
        "deleted_count": 4,
        "total_count": 4,
        "native_deleted_count": 2,
        "langflow_deleted_count": 2,
    }
    assert service.delete_session.await_args_list[0].args == ("db-user", "langflow-1")
    assert service.delete_session.await_args_list[1].args == ("db-user", "langflow-2")
    service.session_ownership_service.release_conversation_sessions.assert_awaited_once_with(
        "db-user", ["native-1", "native-2"]
    )


@pytest.mark.asyncio
async def test_delete_session_removes_native_history_when_langflow_chat_is_enabled(monkeypatch):
    monkeypatch.setattr("services.chat_service.DISABLE_CHAT_WITH_LANGFLOW", False)
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    monkeypatch.delenv("OPENRAG_DISABLE_DB_WORKSPACE_CONFIG", raising=False)
    service = ChatService()
    service.native_chat_history_service.owns_conversation = AsyncMock(return_value=True)
    service.native_chat_history_service.delete = AsyncMock(return_value=True)
    service.session_ownership_service.release_session = AsyncMock()
    service.session_ownership_service.get_conversation_sessions = AsyncMock(return_value=[])
    monkeypatch.setattr("agent.delete_user_conversation", AsyncMock(return_value=False))

    result = await service.delete_session("db-user", "native-1")

    assert result["success"] is True
    assert result["langflow_deleted"] is False
    service.native_chat_history_service.delete.assert_awaited_once_with("native-1", "db-user")
    service.session_ownership_service.release_session.assert_awaited_once_with(
        "db-user", "native-1"
    )


@pytest.mark.asyncio
async def test_delete_session_keeps_ownership_when_legacy_resolution_fails(monkeypatch):
    monkeypatch.setattr("services.chat_service.DISABLE_CHAT_WITH_LANGFLOW", False)
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    monkeypatch.delenv("OPENRAG_DISABLE_DB_WORKSPACE_CONFIG", raising=False)
    service = ChatService()
    service.native_chat_history_service.owns_conversation = AsyncMock(return_value=True)
    service.native_chat_history_service.delete = AsyncMock(return_value=True)
    service.session_ownership_service.get_conversation_sessions = AsyncMock(
        side_effect=RuntimeError("ownership lookup failed")
    )
    service.session_ownership_service.release_session = AsyncMock()
    delete_langflow_session = AsyncMock(return_value=True)
    monkeypatch.setattr(service, "_delete_langflow_session", delete_langflow_session)
    delete_user_conversation = AsyncMock(return_value=True)
    monkeypatch.setattr("agent.delete_user_conversation", delete_user_conversation)

    result = await service.delete_session("db-user", "native-1")

    assert result == {"success": False, "error": "ownership lookup failed"}
    service.native_chat_history_service.delete.assert_awaited_once_with("native-1", "db-user")
    service.session_ownership_service.release_session.assert_not_awaited()
    delete_langflow_session.assert_not_awaited()
    delete_user_conversation.assert_not_awaited()
