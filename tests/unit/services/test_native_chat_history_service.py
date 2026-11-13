from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.native_chat_history_service import NativeChatHistoryService


def test_native_history_opens_the_injected_session_factory():
    session = MagicMock()
    factory = MagicMock(return_value=session)

    service = NativeChatHistoryService(session_factory=factory)

    assert service._factory() is session
    factory.assert_called_once_with()


@pytest.mark.asyncio
async def test_native_history_replays_complete_assistant_turn_with_its_chunks(monkeypatch):
    """History replays tool activity and prose as one assistant turn."""

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    now = datetime.now(UTC)
    conversation = SimpleNamespace(
        id="chat-1",
        title="Question",
        created_at=now,
        last_activity=now,
        filter_id=None,
        total_messages=2,
    )
    rows = [
        SimpleNamespace(
            role="assistant",
            conversation_id="chat-1",
            content="Grounded answer.",
            created_at=now,
            error=False,
            event_data={
                "chunks": [
                    {
                        "type": "response.output_item.done",
                        "item": {
                            "type": "tool_call",
                            "id": "call-1",
                            "tool_name": "search_documents",
                            "inputs": {"search_query": "question"},
                            "results": [],
                            "status": "completed",
                        },
                    }
                ],
                "usage": {"requests": 2},
            },
        ),
    ]

    class Repo:
        def __init__(self, _session):
            pass

        async def list_conversations(self, _user_id):
            return [conversation]

        async def list_messages_for_conversations(self, _conversation_ids):
            return rows

    monkeypatch.setattr("services.native_chat_history_service.ChatHistoryRepo", Repo)

    history = await NativeChatHistoryService(session_factory=Session).history("user")

    message = history["conversations"][0]["messages"][0]
    assert message["content"] == "Grounded answer."
    assert message["chunks"][0]["item"] == {
        "type": "tool_call",
        "id": "call-1",
        "tool_name": "search_documents",
        "inputs": {"search_query": "question"},
        "results": [],
        "status": "completed",
    }
    assert message["response_data"] == {"usage": {"requests": 2}}
