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


def test_format_provider_error_message_extracts_ibm_iam_error_message():
    raw = (
        'Failed to authenticate with IBM Watson: {"errorCode":"BXNIM0415E",'
        '"errorMessage":"Provided API key could not be found.",'
        '"context":{"requestId":"abc","url":"https://iam.cloud.ibm.com"}}'
    )
    assert agent_module._format_provider_error_message(Exception(raw)) == (
        "Failed to authenticate with IBM Watson: Provided API key could not be found."
    )


def test_format_provider_error_message_keeps_plain_text():
    msg = "Rate limit exceeded for watsonx.ai. Please try again later."
    assert agent_module._format_provider_error_message(Exception(msg)) == msg


def test_provider_error_display_text_keeps_partial_answer():
    assert agent_module._provider_error_display_text(
        "Rate limit exceeded", "Partial answer so far"
    ) == ("Partial answer so far\n\nRate limit exceeded")


def test_resolve_error_store_id_ignores_cold_previous_response_id():
    assert (
        agent_module._resolve_error_store_id(
            None,
            "resp_cold",
            previous_loaded_from_memory=False,
        )
        is None
    )
    assert (
        agent_module._resolve_error_store_id(
            None,
            "resp_warm",
            previous_loaded_from_memory=True,
        )
        == "resp_warm"
    )
    assert (
        agent_module._resolve_error_store_id(
            "resp_stream",
            "resp_warm",
            previous_loaded_from_memory=True,
        )
        == "resp_stream"
    )


@pytest.fixture
def store_in_memory(monkeypatch):
    stored: list[tuple[str, str]] = []

    async def _store(user_id, response_id, conversation_state):
        stored.append((user_id, response_id))
        if user_id not in agent_module.active_conversations:
            agent_module.active_conversations[user_id] = {}
        agent_module.active_conversations[user_id][response_id] = conversation_state

    monkeypatch.setattr(agent_module, "store_conversation_thread", _store)
    return stored


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

    # No real response_id yet — do not invent synthetic error_* conversations.
    assert store_in_memory == []
    assert agent_module.active_conversations.get(user_id, {}) == {}


@pytest.mark.asyncio
async def test_langflow_stream_persists_error_onto_existing_thread(monkeypatch, store_in_memory):
    provider_message = "Invalid API key for Anthropic. Check your credentials."

    async def raise_provider_error(*_args, **_kwargs) -> AsyncIterator[bytes]:
        raise Exception(provider_message)
        yield b""  # pragma: no cover

    monkeypatch.setattr(agent_module, "async_stream", raise_provider_error)

    user_id = "test-provider-error-existing"
    previous_id = "resp_existing_thread"
    agent_module.active_conversations[user_id] = {
        previous_id: {
            "messages": [{"role": "user", "content": "earlier"}],
            "created_at": None,
            "last_activity": None,
        }
    }

    chunks = await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(
            langflow_client=object(),
            flow_id="flow-id",
            prompt="hello",
            user_id=user_id,
            previous_response_id=previous_id,
        )
    )

    assert chunks[0]["error"]["message"] == provider_message
    assert store_in_memory == [(user_id, previous_id)]
    assert not any(rid.startswith("error_") for _, rid in store_in_memory)

    stored = agent_module.active_conversations[user_id][previous_id]
    error_messages = [m for m in stored["messages"] if m.get("error")]
    assert len(error_messages) == 1
    assert error_messages[0]["content"] == provider_message


@pytest.mark.asyncio
async def test_langflow_stream_skips_persist_for_cold_previous_response_id(
    monkeypatch, store_in_memory
):
    provider_message = "Permission denied: model access not authorized."

    async def raise_provider_error(*_args, **_kwargs) -> AsyncIterator[bytes]:
        raise Exception(provider_message)
        yield b""  # pragma: no cover

    monkeypatch.setattr(agent_module, "async_stream", raise_provider_error)

    user_id = "test-provider-error-cold"
    previous_id = "resp_not_in_memory"
    agent_module.active_conversations.pop(user_id, None)

    chunks = await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(
            langflow_client=object(),
            flow_id="flow-id",
            prompt="hello",
            user_id=user_id,
            previous_response_id=previous_id,
        )
    )

    assert chunks[0]["error"]["message"] == provider_message
    # Cold previous_response_id must not overwrite conversation metadata.
    assert store_in_memory == []
    assert previous_id not in agent_module.active_conversations.get(user_id, {})


@pytest.mark.asyncio
async def test_langflow_stream_keeps_partial_text_with_provider_error(monkeypatch, store_in_memory):
    provider_message = "Rate limit exceeded for watsonx.ai."

    async def partial_then_fail(*_args, **_kwargs) -> AsyncIterator[bytes]:
        yield (
            json.dumps(
                {
                    "id": "resp_partial",
                    "delta": {"content": "Here is a partial answer"},
                }
            )
            + "\n"
        ).encode("utf-8")
        raise Exception(provider_message)

    monkeypatch.setattr(agent_module, "async_stream", partial_then_fail)

    user_id = "test-provider-error-partial"
    agent_module.active_conversations.pop(user_id, None)

    chunks = await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(
            langflow_client=object(),
            flow_id="flow-id",
            prompt="hello",
            user_id=user_id,
        )
    )

    assert len(chunks) == 2
    assert chunks[0]["delta"]["content"] == "Here is a partial answer"
    assert chunks[1]["error"]["message"] == (f"Here is a partial answer\n\n{provider_message}")
    assert store_in_memory == [(user_id, "resp_partial")]


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
    assert store_in_memory == []
    assert agent_module.active_conversations.get(user_id, {}) == {}
