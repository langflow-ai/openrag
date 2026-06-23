import sys
from pathlib import Path
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


@pytest.mark.asyncio
async def test_upload_context_chat_passes_owner_metadata(monkeypatch):
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
