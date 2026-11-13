import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.chat_service import ChatService  # noqa: E402
from services.document_index_writer import DocumentIndexContext  # noqa: E402


@pytest.mark.asyncio
async def test_langflow_chat_passes_owner_metadata(monkeypatch):
    # This test asserts the Langflow path, so pin the static deployment switch off.
    monkeypatch.setattr("services.chat_service.DISABLE_CHAT_WITH_LANGFLOW", False)

    # Mock settings / clients dependencies
    fake_langflow_client = MagicMock()
    monkeypatch.setattr(
        "config.settings.clients.ensure_langflow_client",
        AsyncMock(return_value=fake_langflow_client),
    )
    monkeypatch.setattr(
        "utils.langflow_headers.add_provider_credentials_to_headers",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(
                embedding_model="text-embedding-3-small",
                embedding_provider=None,
                chunk_size=1000,
                chunk_overlap=200,
                index_name="documents",
            )
        ),
    )

    # Mock async_langflow_chat to prevent actual network/langflow calls
    monkeypatch.setattr(
        "agent.async_langflow_chat",
        AsyncMock(return_value=("some response", "response-id", [])),
    )

    # Capture the context passed to LangflowIngestTokenService.create_token
    captured_context = []

    def mock_create_token(self, context):
        captured_context.append(context)
        return "fake-ingest-token"

    monkeypatch.setattr(
        "services.langflow_ingest_token_service.LangflowIngestTokenService.create_token",
        mock_create_token,
    )

    # Instantiate ChatService and invoke langflow_chat with specific owner metadata
    chat_svc = ChatService()
    await chat_svc.langflow_chat(
        prompt="hello",
        owner="user-123",
        owner_name="Test User",
        owner_email="test@example.com",
    )

    # Assert that DocumentIndexContext was created with correct owner details
    assert len(captured_context) == 1
    context = captured_context[0]
    assert isinstance(context, DocumentIndexContext)
    assert context.owner == "user-123"
    assert context.owner_name == "Test User"
    assert context.owner_email == "test@example.com"
    assert context.embedding_provider == "openai"


@pytest.mark.asyncio
async def test_upload_context_chat_passes_owner_metadata(monkeypatch):
    # This test asserts the Langflow path, so pin the static deployment switch off.
    monkeypatch.setattr("services.chat_service.DISABLE_CHAT_WITH_LANGFLOW", False)

    # Mock settings / clients dependencies
    fake_langflow_client = MagicMock()
    monkeypatch.setattr(
        "config.settings.clients.ensure_langflow_client",
        AsyncMock(return_value=fake_langflow_client),
    )
    monkeypatch.setattr(
        "utils.langflow_headers.add_provider_credentials_to_headers",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(
                embedding_model="text-embedding-3-small",
                embedding_provider=None,
                chunk_size=1000,
                chunk_overlap=200,
                index_name="documents",
            )
        ),
    )

    # Mock async_langflow to prevent actual network/langflow calls
    monkeypatch.setattr(
        "services.chat_service.async_langflow",
        AsyncMock(return_value=("some response", "response-id")),
    )

    # Capture the context passed to LangflowIngestTokenService.create_token
    captured_context = []

    def mock_create_token(self, context):
        captured_context.append(context)
        return "fake-ingest-token"

    monkeypatch.setattr(
        "services.langflow_ingest_token_service.LangflowIngestTokenService.create_token",
        mock_create_token,
    )

    # Instantiate ChatService and invoke upload_context_chat with specific owner metadata
    chat_svc = ChatService()
    await chat_svc.upload_context_chat(
        document_content="content",
        filename="doc.txt",
        owner="user-456",
        owner_name="Another User",
        owner_email="another@example.com",
        endpoint="langflow",
    )

    # Assert that DocumentIndexContext was created with correct owner details
    assert len(captured_context) == 1
    context = captured_context[0]
    assert isinstance(context, DocumentIndexContext)
    assert context.owner == "user-456"
    assert context.owner_name == "Another User"
    assert context.owner_email == "another@example.com"
    assert context.embedding_provider == "openai"


@pytest.mark.asyncio
async def test_native_chat_session_delete_releases_its_ownership(monkeypatch):
    monkeypatch.setattr("services.chat_service.DISABLE_CHAT_WITH_LANGFLOW", True)
    delete = AsyncMock(return_value=True)
    owns_conversation = AsyncMock(return_value=True)
    release_session = AsyncMock(return_value=True)
    service = ChatService()
    monkeypatch.setattr(service.native_chat_history_service, "owns_conversation", owns_conversation)
    monkeypatch.setattr(service.native_chat_history_service, "delete", delete)
    monkeypatch.setattr(service.session_ownership_service, "release_session", release_session)

    result = await service.delete_session("user-1", "chat-1")

    assert result["success"] is True
    owns_conversation.assert_awaited_once_with("chat-1", "user-1")
    delete.assert_awaited_once_with("chat-1", "user-1")
    release_session.assert_awaited_once_with("user-1", "chat-1")


@pytest.mark.asyncio
async def test_langflow_session_delete_removes_its_native_history_mirror(monkeypatch):
    monkeypatch.setattr("services.chat_service.DISABLE_CHAT_WITH_LANGFLOW", False)
    service = ChatService()
    native_delete = AsyncMock(return_value=True)
    monkeypatch.setattr(
        service.native_chat_history_service, "owns_conversation", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(service.native_chat_history_service, "delete", native_delete)
    monkeypatch.setattr(
        "services.session_ownership_service.session_ownership_service.get_conversation_sessions",
        AsyncMock(return_value=["langflow-1"]),
    )
    monkeypatch.setattr(ChatService, "_delete_langflow_session", AsyncMock(return_value=True))
    monkeypatch.setattr("agent.delete_user_conversation", AsyncMock(return_value=True))

    result = await service.delete_session("user-1", "langflow-1")

    assert result["success"] is True
    assert result["native_deleted"] is True
    native_delete.assert_awaited_once_with("langflow-1", "user-1")
