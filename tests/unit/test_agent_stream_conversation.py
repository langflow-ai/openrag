"""Unit tests for conversation persistence on the streamed chat path.

The Responses API nests the response id under `response` and sends answer text
as a bare string on `response.output_text.delta`. async_chat_stream used to look
for both at the top level, so `response_id` stayed None, the persistence call was
skipped entirely, and the assistant message was stored empty.
"""

import json

import pytest

import agent


def _chunk(payload: dict) -> bytes:
    return (json.dumps(payload) + "\n").encode("utf-8")


# Shapes taken from a real Azure AI Foundry openai/v1 stream, including the
# function-call events that appear whenever retrieval runs.
RESPONSE_ID = "resp_0c477eeda12b57ea006a80f5b740bc8196"
STREAM = [
    _chunk({"type": "response.created", "response": {"id": RESPONSE_ID, "status": "in_progress"}}),
    _chunk({"type": "response.in_progress", "response": {"id": RESPONSE_ID}}),
    _chunk({"type": "response.output_item.added", "item": {"id": "fc_1", "type": "function_call"}}),
    _chunk(
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "fc_1",
            "delta": '{"query": "costco earnings"}',
        }
    ),
    _chunk({"type": "response.output_text.delta", "item_id": "msg_1", "delta": "Costco "}),
    _chunk({"type": "response.output_text.delta", "item_id": "msg_1", "delta": "earnings rose."}),
    _chunk({"type": "keepalive", "delta": None, "sequence_number": 7}),
    _chunk(
        {
            "type": "response.completed",
            "response": {"id": RESPONSE_ID, "usage": {"input_tokens": 12, "output_tokens": 5}},
        }
    ),
]


@pytest.fixture
def captured(monkeypatch):
    """Drive async_chat_stream over the canned stream, capturing what it persists."""
    calls: list[dict] = []
    claimed: list[tuple[str, str]] = []

    async def fake_stream(*args, **kwargs):
        for chunk in STREAM:
            yield chunk

    async def fake_store(user_id, response_id, conversation_state, endpoint="langflow"):
        calls.append(
            {
                "user_id": user_id,
                "response_id": response_id,
                "endpoint": endpoint,
                "messages": list(conversation_state.get("messages", [])),
                "claimed": claimed,
            }
        )

    async def fake_claim(user_id, response_id):
        claimed.append((user_id, response_id))

    monkeypatch.setattr(agent, "async_stream", fake_stream)
    monkeypatch.setattr(agent, "store_conversation_thread", fake_store)
    monkeypatch.setattr(agent, "claim_session_ownership", fake_claim)
    agent.active_conversations.clear()
    return calls


@pytest.mark.asyncio
async def test_streamed_conversation_is_persisted(captured):
    async for _ in agent.async_chat_stream(object(), "costco earnings", "u1", "gpt-4.1-nano"):
        pass

    assert len(captured) == 1, "conversation was not persisted"
    assert captured[0]["response_id"] == RESPONSE_ID


@pytest.mark.asyncio
async def test_streamed_conversation_records_chat_endpoint(captured):
    """Stored as "langflow" it would never appear in the Chat sidebar."""
    async for _ in agent.async_chat_stream(object(), "costco earnings", "u1", "gpt-4.1-nano"):
        pass

    assert captured[0]["endpoint"] == "chat"


@pytest.mark.asyncio
async def test_streamed_conversation_claims_session_ownership(captured):
    """Unclaimed sessions read as 404 to _assert_owns, so they can't be deleted."""
    async for _ in agent.async_chat_stream(object(), "costco earnings", "u1", "gpt-4.1-nano"):
        pass

    assert captured[0]["claimed"] == [("u1", RESPONSE_ID)]


@pytest.mark.asyncio
async def test_non_streaming_conversation_is_labelled_and_claimed(monkeypatch):
    """The non-streaming path shares both gaps: endpoint label and ownership."""
    stored: list[dict] = []
    claimed: list[tuple[str, str]] = []

    async def fake_response(client, prompt, model, **kwargs):
        return "Costco earnings rose.", RESPONSE_ID, object()

    async def fake_store(user_id, response_id, conversation_state, endpoint="langflow"):
        stored.append({"response_id": response_id, "endpoint": endpoint})

    async def fake_claim(user_id, response_id):
        claimed.append((user_id, response_id))

    monkeypatch.setattr(agent, "async_response", fake_response)
    monkeypatch.setattr(agent, "store_conversation_thread", fake_store)
    monkeypatch.setattr(agent, "claim_session_ownership", fake_claim)
    agent.active_conversations.clear()

    await agent.async_chat(object(), "costco earnings", "u1", "gpt-4.1-nano")

    assert stored and stored[0]["endpoint"] == "chat"
    assert claimed == [("u1", RESPONSE_ID)]


@pytest.mark.asyncio
async def test_streamed_assistant_message_holds_answer_text(captured):
    async for _ in agent.async_chat_stream(object(), "costco earnings", "u1", "gpt-4.1-nano"):
        pass

    assistant = [m for m in captured[0]["messages"] if m["role"] == "assistant"]
    assert len(assistant) == 1
    # Answer text only — tool-call arguments share the `delta` field name and
    # must not be spliced into the stored message.
    assert assistant[0]["content"] == "Costco earnings rose."
    assert "query" not in assistant[0]["content"]
    assert assistant[0]["response_data"]["usage"]["output_tokens"] == 5
