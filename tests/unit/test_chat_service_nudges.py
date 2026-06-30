"""Tests for ChatService langflow_nudges_chat extraction logic."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import agent
from services.chat_service import ChatService


@pytest.mark.asyncio
async def test_langflow_nudges_chat_with_chunks_in_memory(monkeypatch):
    """Ensure in-memory conversation chunks are formatted into the nudges prompt."""
    monkeypatch.setattr("services.chat_service.LANGFLOW_URL", "http://localhost:7860")
    monkeypatch.setattr("services.chat_service.NUDGES_FLOW_ID", "nudges-flow-id")

    # Mock clients
    mock_lf_client = MagicMock()
    monkeypatch.setattr(
        "services.chat_service.clients.ensure_langflow_client",
        AsyncMock(return_value=mock_lf_client),
    )

    # Prepopulate active_conversations with a message containing tool call chunks
    test_user_id = "test-user"
    test_resp_id = "test-resp"

    chunks_data = [
        {
            "item": {
                "type": "tool_call",
                "tool_name": "Retrieval",
                "results": [{"filename": "doc.md", "text": "Important retrieved content."}],
            }
        }
    ]

    agent.active_conversations[test_user_id] = {
        test_resp_id: {
            "messages": [
                {"role": "user", "content": "What is OpenRAG?"},
                {"role": "assistant", "content": "It is an AI platform.", "chunks": chunks_data},
            ]
        }
    }

    # Mock async_langflow_chat to capture prompt
    captured_prompt = None

    async def mock_async_lf_chat(client, flow_id, prompt, user_id, **kwargs):
        nonlocal captured_prompt
        captured_prompt = prompt
        return "Nudge 1\nNudge 2", "nudge-resp", []

    monkeypatch.setattr(agent, "async_langflow_chat", mock_async_lf_chat)

    svc = ChatService()
    res = await svc.langflow_nudges_chat(user_id=test_user_id, previous_response_id=test_resp_id)

    assert res["response"] == "Nudge 1\nNudge 2"
    assert captured_prompt is not None
    assert "user: What is OpenRAG?" in captured_prompt
    assert "assistant: It is an AI platform." in captured_prompt
    assert "Context Chunks:" in captured_prompt
    assert "Important retrieved content." in captured_prompt

    # Clean up
    agent.active_conversations.pop(test_user_id, None)


@pytest.mark.asyncio
async def test_langflow_nudges_chat_with_chunks_langflow_history(monkeypatch):
    """Ensure persistent Langflow history chunks are formatted into the nudges prompt."""
    monkeypatch.setattr("services.chat_service.LANGFLOW_URL", "http://localhost:7860")
    monkeypatch.setattr("services.chat_service.NUDGES_FLOW_ID", "nudges-flow-id")

    # Mock clients
    mock_lf_client = MagicMock()
    monkeypatch.setattr(
        "services.chat_service.clients.ensure_langflow_client",
        AsyncMock(return_value=mock_lf_client),
    )

    # Ensure active_conversations is empty for this test
    test_user_id = "lf-user"
    test_resp_id = "lf-resp"
    agent.active_conversations.pop(test_user_id, None)

    # Mock langflow_history_service.get_session_messages
    lf_messages = [
        {"role": "user", "content": "Tell me about security."},
        {
            "role": "assistant",
            "content": "Security is robust.",
            "chunks": [
                {
                    "item": {
                        "type": "tool_call",
                        "tool_name": "OpenSearch",
                        "results": {"hits": ["Security info chunk."]},
                    }
                }
            ],
        },
    ]
    mock_get_messages = AsyncMock(return_value=lf_messages)
    from services.langflow_history_service import langflow_history_service

    monkeypatch.setattr(langflow_history_service, "get_session_messages", mock_get_messages)

    # Mock async_langflow_chat to capture prompt
    captured_prompt = None

    async def mock_async_lf_chat(client, flow_id, prompt, user_id, **kwargs):
        nonlocal captured_prompt
        captured_prompt = prompt
        return "Nudge A\nNudge B", "nudge-resp", []

    monkeypatch.setattr(agent, "async_langflow_chat", mock_async_lf_chat)

    svc = ChatService()
    res = await svc.langflow_nudges_chat(user_id=test_user_id, previous_response_id=test_resp_id)

    assert res["response"] == "Nudge A\nNudge B"
    assert captured_prompt is not None
    assert "user: Tell me about security." in captured_prompt
    assert "Context Chunks:" in captured_prompt
    assert "Security info chunk." in captured_prompt
