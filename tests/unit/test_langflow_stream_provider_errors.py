"""Provider errors must reach the client as a final stream error chunk.

These tests mock the upstream stream to raise exceptions shaped like real
provider failures (watsonx rate limit, invalid key, permission). That proves
the yield path without hardcoding a raise in production code.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

import agent as agent_module


def test_format_provider_error_message_extracts_embedded_json():
    raw = (
        'Provider request failed: {"error": {"message": '
        '"Incorrect API key provided", "type": "invalid_request_error"}}'
    )
    assert (
        agent_module._format_provider_error_message(Exception(raw))
        == "Provider request failed: Incorrect API key provided"
    )


def test_format_provider_error_message_keeps_plain_text():
    msg = "Rate limit exceeded for watsonx.ai. Please try again later."
    assert agent_module._format_provider_error_message(Exception(msg)) == msg


@pytest.fixture
def store_in_memory(monkeypatch):
    async def _store(user_id, response_id, conversation_state):
        if user_id not in agent_module.active_conversations:
            agent_module.active_conversations[user_id] = {}
        agent_module.active_conversations[user_id][response_id] = conversation_state

    monkeypatch.setattr(agent_module, "store_conversation_thread", _store)
    return _store


async def _collect_error_chunks(stream) -> list[dict]:
    chunks: list[dict] = []
    async for raw in stream:
        chunks.append(json.loads(raw.decode("utf-8")))
    return chunks


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_message",
    [
        "Rate limit exceeded for watsonx.ai. Please try again later.",
        "Invalid API key for Anthropic. Check your credentials.",
        "Permission denied: model access not authorized for this project.",
        "Quota exceeded: you have reached your monthly token limit.",
    ],
)
async def test_langflow_stream_yields_provider_error_chunk(
    monkeypatch, store_in_memory, provider_message: str
):
    async def raise_provider_error(*_args, **_kwargs) -> AsyncIterator[bytes]:
        raise Exception(provider_message)
        yield b""  # pragma: no cover — keep this an async generator

    monkeypatch.setattr(agent_module, "async_stream", raise_provider_error)

    user_id = "test-provider-error-user"
    agent_module.active_conversations.pop(user_id, None)

    chunks = await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(
            langflow_client=object(),
            flow_id="flow-id",
            prompt="hello",
            user_id=user_id,
        )
    )

    assert len(chunks) == 1
    error_chunk = chunks[0]
    assert error_chunk["status"] == "failed"
    assert error_chunk["finish_reason"] == "error"
    assert error_chunk["error"]["message"] == provider_message

    # Live stream and history must use the same user-facing text.
    conversation = agent_module.active_conversations[user_id]
    stored = next(iter(conversation.values()))
    error_messages = [m for m in stored["messages"] if m.get("error")]
    assert len(error_messages) == 1
    assert error_messages[0]["content"] == provider_message


@pytest.mark.asyncio
async def test_chat_stream_yields_provider_error_chunk(monkeypatch, store_in_memory):
    provider_message = "Permission denied: model access not authorized for this project."

    async def raise_provider_error(*_args, **_kwargs) -> AsyncIterator[bytes]:
        raise Exception(provider_message)
        yield b""  # pragma: no cover

    monkeypatch.setattr(agent_module, "async_stream", raise_provider_error)

    user_id = "test-chat-provider-error-user"
    agent_module.active_conversations.pop(user_id, None)

    chunks = await _collect_error_chunks(
        agent_module.async_chat_stream(
            async_client=object(),
            prompt="hello",
            user_id=user_id,
            model="gpt-4.1-mini",
        )
    )

    assert len(chunks) == 1
    assert chunks[0]["error"]["message"] == provider_message

    conversation = agent_module.active_conversations[user_id]
    stored = next(iter(conversation.values()))
    error_messages = [m for m in stored["messages"] if m.get("error")]
    assert error_messages[0]["content"] == provider_message
