"""Langflow stream lifecycle and provider-error regressions.

Only the upstream provider is replaced; cancellation regressions use the real
conversation store and ownership guard, including durable SQLite ownership.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace

import anyio
import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import agent as agent_module
from api.chat import ChatBody, _assert_owns, langflow_endpoint
from services.conversation_persistence_service import ConversationPersistenceService
from services.session_ownership_service import SessionOwnershipService


def test_format_provider_error_message_extracts_embedded_json():
    raw = (
        'Provider request failed: {"error": {"message": '
        '"Incorrect API key provided", "type": "invalid_request_error"}}'
    )
    assert (
        agent_module._format_provider_error_message(Exception(raw)) == "Incorrect API key provided"
    )


def test_format_provider_error_message_extracts_ibm_iam_error_message():
    raw = (
        'Failed to authenticate with IBM Watson: {"errorCode":"BXNIM0415E",'
        '"errorMessage":"Provided API key could not be found.",'
        '"context":{"requestId":"abc","url":"https://iam.cloud.ibm.com"}}'
    )
    assert agent_module._format_provider_error_message(Exception(raw)) == (
        "Provided API key is Invalid."
    )


def test_format_provider_error_message_keeps_plain_text():
    msg = "Rate limit exceeded for watsonx.ai. Please try again later."
    assert agent_module._format_provider_error_message(Exception(msg)) == msg


def test_provider_error_display_text_keeps_partial_answer():
    assert agent_module._provider_error_display_text(
        "Rate limit exceeded", "Partial answer so far"
    ) == ("Partial answer so far\n\nRate limit exceeded")


def test_provider_error_display_text_drops_error_like_partial():
    partial = (
        "Failed to initialize IBM WatsonX embedding model. Error: "
        '{"errorMessage":"Provided API key could not be found."}'
    )
    assert (
        agent_module._provider_error_display_text("Provided API key is Invalid.", partial)
        == "Provided API key is Invalid."
    )


def test_resolve_conversation_store_id_prefers_warm_thread():
    cold_id = agent_module._resolve_conversation_store_id(
        None,
        "resp_cold",
        previous_loaded_from_memory=False,
        mint_if_missing=True,
    )
    # Cold previous ids must not be reused (would overwrite metadata); mint a new id.
    assert cold_id != "resp_cold"
    assert not cold_id.startswith("error_")

    assert (
        agent_module._resolve_conversation_store_id(
            None,
            "resp_warm",
            previous_loaded_from_memory=True,
        )
        == "resp_warm"
    )
    assert (
        agent_module._resolve_conversation_store_id(
            "resp_stream",
            "resp_warm",
            previous_loaded_from_memory=True,
        )
        == "resp_warm"
    )


@pytest.fixture
def store_in_memory(monkeypatch):
    stored: list[tuple[str, str]] = []
    claimed: list[tuple[str, str]] = []

    async def _store(user_id, response_id, conversation_state):
        stored.append((user_id, response_id))
        if user_id not in agent_module.active_conversations:
            agent_module.active_conversations[user_id] = {}
        agent_module.active_conversations[user_id][response_id] = conversation_state

    class _Ownership:
        async def claim_session(self, user_id, session_id):
            claimed.append((user_id, session_id))

        async def get_session_owner(self, session_id):
            return next((user_id for user_id, sid in claimed if sid == session_id), None)

    monkeypatch.setattr(agent_module, "store_conversation_thread", _store)
    monkeypatch.setattr(
        "services.session_ownership_service.session_ownership_service",
        _Ownership(),
    )
    return {"stored": stored, "claimed": claimed}


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

    # Failed first turns still get a real store id (UUID, not error_*).
    assert len(store_in_memory["stored"]) == 1
    stored_user, stored_id = store_in_memory["stored"][0]
    assert stored_user == user_id
    assert not stored_id.startswith("error_")
    assert error_chunk.get("id") == stored_id
    assert stored_id in agent_module.active_conversations.get(user_id, {})


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
    assert store_in_memory["stored"] == [(user_id, previous_id)]
    assert store_in_memory["claimed"] == [(user_id, previous_id)]
    assert not any(rid.startswith("error_") for _, rid in store_in_memory["stored"])

    stored = agent_module.active_conversations[user_id][previous_id]
    error_messages = [m for m in stored["messages"] if m.get("error")]
    assert len(error_messages) == 1
    assert error_messages[0]["content"] == provider_message


@pytest.mark.asyncio
async def test_langflow_follow_up_after_error_reuses_store_id(monkeypatch, store_in_memory):
    """Retrying in the same chat must not create a second sidebar conversation."""
    provider_message = "Rate limit exceeded for watsonx.ai."
    stream_calls: list[dict] = []

    async def raise_provider_error(*_args, **kwargs) -> AsyncIterator[bytes]:
        stream_calls.append(kwargs)
        raise Exception(provider_message)
        yield b""  # pragma: no cover

    monkeypatch.setattr(agent_module, "async_stream", raise_provider_error)

    user_id = "test-provider-error-follow-up"
    existing_id = "resp_failed_thread"
    agent_module.active_conversations[user_id] = {
        existing_id: {
            "messages": [
                {"role": "user", "content": "first"},
                {
                    "role": "assistant",
                    "content": "Provided API key could not be found.",
                    "error": True,
                },
            ],
            "created_at": None,
            "last_activity": None,
        }
    }

    # Client keeps conversation_id after an error but omits previous_response_id
    # so Langflow starts fresh while OpenRAG appends to the same sidebar thread.
    chunks = await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(
            langflow_client=object(),
            flow_id="flow-id",
            prompt="retry hello",
            user_id=user_id,
            conversation_id=existing_id,
            previous_response_id=None,
        )
    )

    assert chunks[0]["error"]["message"] == provider_message
    assert store_in_memory["stored"] == [(user_id, existing_id)]
    assert list(agent_module.active_conversations[user_id].keys()) == [existing_id]
    # Fresh Langflow session, same OpenRAG conversation id.
    assert stream_calls[0].get("previous_response_id") is None
    stored_messages = agent_module.active_conversations[user_id][existing_id]["messages"]
    assert [m["role"] for m in stored_messages if m["role"] != "system"][-2:] == [
        "user",
        "assistant",
    ]


@pytest.mark.asyncio
async def test_langflow_follow_up_ignores_broken_previous_response_id(monkeypatch, store_in_memory):
    """Even if the client still sends a failed Langflow session id, do not chain it."""
    provider_message = "Invalid API key for Anthropic. Check your credentials."
    stream_calls: list[dict] = []

    async def raise_provider_error(*_args, **kwargs) -> AsyncIterator[bytes]:
        stream_calls.append(kwargs)
        raise Exception(provider_message)
        yield b""  # pragma: no cover

    monkeypatch.setattr(agent_module, "async_stream", raise_provider_error)

    user_id = "test-provider-error-broken-session"
    existing_id = "resp_broken_langflow"
    agent_module.active_conversations[user_id] = {
        existing_id: {
            "messages": [
                {"role": "user", "content": "first"},
                {
                    "role": "assistant",
                    "content": provider_message,
                    "error": True,
                },
            ],
            "created_at": None,
            "last_activity": None,
        }
    }

    chunks = await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(
            langflow_client=object(),
            flow_id="flow-id",
            prompt="retry hello",
            user_id=user_id,
            conversation_id=existing_id,
            previous_response_id=existing_id,
        )
    )

    assert chunks[0]["error"]["message"] == provider_message
    assert stream_calls[0].get("previous_response_id") is None
    assert store_in_memory["stored"] == [(user_id, existing_id)]


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
    # Cold previous_response_id must not overwrite conversation metadata —
    # persist under a freshly minted id instead.
    assert len(store_in_memory["stored"]) == 1
    stored_user, stored_id = store_in_memory["stored"][0]
    assert stored_user == user_id
    assert stored_id != previous_id
    assert not stored_id.startswith("error_")
    assert previous_id not in agent_module.active_conversations.get(user_id, {})
    assert stored_id in agent_module.active_conversations.get(user_id, {})


@pytest.mark.asyncio
async def test_langflow_stream_treats_credential_dump_content_as_error(
    monkeypatch, store_in_memory
):
    """WatsonX failures are often streamed as assistant text with no exception."""
    dump = (
        "Failed to initialize IBM WatsonX embedding model: Attempt of authenticating "
        "connection to service failed, please validate your credentials. Error: "
        '{"errorCode":"BXNIM0415E","errorMessage":"Provided API key could not be found."} '
        "IBM WatsonX requires additional configuration parameters "
        "(API endpoint URL and project ID). An error occurred while generating a response."
    )

    async def stream_dump(*_args, **_kwargs) -> AsyncIterator[bytes]:
        yield (json.dumps({"id": "resp_dump", "delta": {"content": dump}}) + "\n").encode("utf-8")

    monkeypatch.setattr(agent_module, "async_stream", stream_dump)

    user_id = "test-provider-error-content-dump"
    agent_module.active_conversations.pop(user_id, None)

    chunks = await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(
            langflow_client=object(),
            flow_id="flow-id",
            prompt="hello",
            user_id=user_id,
        )
    )

    assert any(c.get("status") == "failed" for c in chunks)
    error_chunk = next(c for c in chunks if c.get("status") == "failed")
    assert "{" not in error_chunk["error"]["message"]
    assert "Provided API key is Invalid" in error_chunk["error"]["message"]
    assert store_in_memory["stored"] == [(user_id, "resp_dump")] * 2
    assert store_in_memory["claimed"] == [(user_id, "resp_dump")]
    stored = agent_module.active_conversations[user_id]["resp_dump"]
    assert stored["messages"][-1]["error"] is True
    assert "{" not in stored["messages"][-1]["content"]


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
    assert store_in_memory["stored"] == [(user_id, "resp_partial")] * 2
    assert store_in_memory["claimed"] == [(user_id, "resp_partial")]


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
    assert len(store_in_memory["stored"]) == 1
    stored_user, stored_id = store_in_memory["stored"][0]
    assert stored_user == user_id
    assert not stored_id.startswith("error_")
    assert chunks[0].get("id") == stored_id
    assert stored_id in agent_module.active_conversations.get(user_id, {})


@pytest_asyncio.fixture(params=["db", "hybrid", "files"])
async def durable_stream_stores(request, monkeypatch, tmp_path):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", request.param)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(
        "services.session_ownership_service.get_data_file",
        lambda name: str(tmp_path / name),
    )
    ownership = SessionOwnershipService(session_factory=factory)
    persistence = ConversationPersistenceService(
        storage_file=str(tmp_path / "conversations.json"), session_factory=factory
    )
    monkeypatch.setattr("services.session_ownership_service.session_ownership_service", ownership)
    monkeypatch.setattr(agent_module, "conversation_persistence", persistence)
    monkeypatch.setattr(agent_module, "active_conversations", {})
    yield ownership, persistence, factory
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("abort", ["close", "cancel"])
async def test_aborted_langflow_stream_keeps_owned_id_and_partial_turn(
    monkeypatch, durable_stream_stores, abort
):
    ownership, persistence, factory = durable_stream_stores
    waiting = asyncio.Event()
    upstream_closed = asyncio.Event()
    calls = []

    async def upstream(*_args, **kwargs):
        calls.append(kwargs.get("previous_response_id"))
        try:
            yield b'{"id":"resp-first","delta":{"content":"Partial answer"}}\n'
            waiting.set()
            await asyncio.Event().wait()
        finally:
            upstream_closed.set()

    monkeypatch.setattr(agent_module, "async_stream", upstream)
    stream = agent_module.async_langflow_chat_stream(object(), "flow", "First question", "alice")
    chunk = json.loads(await anext(stream))
    # The ID must already be durable when it first crosses the generator boundary.
    await _assert_owns(chunk["id"], "alice")
    assert (await persistence.get_conversation_thread("alice", chunk["id"]))["total_messages"] >= 1
    if abort == "close":
        await stream.aclose()
    else:
        pending = asyncio.create_task(anext(stream))
        await waiting.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    assert upstream_closed.is_set()
    # Reload ownership rather than relying on the live service's cache.
    reloaded = SessionOwnershipService(session_factory=factory)
    assert await reloaded.get_session_owner(chunk["id"]) == "alice"
    with pytest.raises(HTTPException) as forbidden:
        await _assert_owns(chunk["id"], "mallory")
    assert forbidden.value.status_code == 403
    with pytest.raises(HTTPException) as missing:
        await _assert_owns("unknown-session", "alice")
    assert missing.value.status_code == 404

    async def continuation(*_args, **kwargs):
        calls.append(kwargs.get("previous_response_id"))
        yield b'{"id":"resp-next","response_id":"resp-next-alias","delta":{"content":"Next"}}\n'

    monkeypatch.setattr(agent_module, "async_stream", continuation)
    await _assert_owns(chunk["id"], "alice")
    followup = agent_module.async_langflow_chat_stream(
        object(),
        "flow",
        "Follow-up",
        "alice",
        previous_response_id=chunk["id"],
        conversation_id=chunk["id"],
    )
    next_chunk = json.loads(await anext(followup))
    await _assert_owns(next_chunk["id"], "alice")
    await _assert_owns(next_chunk["response_id"], "alice")
    assert await _collect_error_chunks(followup) == []
    assert calls == [None, "resp-first"]  # Never replay the interrupted prompt.
    conversations = await persistence.get_user_conversations("alice")
    assert list(conversations) == ["resp-first"]  # Stable sidebar id, changing response ids.
    messages = agent_module.active_conversations["alice"]["resp-first"]["messages"]
    assert [(m["role"], m["content"]) for m in messages if m["role"] != "system"] == [
        ("user", "First question"),
        ("assistant", "Partial answer"),
        ("user", "Follow-up"),
        ("assistant", "Next"),
    ]
    assert conversations["resp-first"]["total_messages"] == 4

    # SDK callers may only carry the changing response ID, not conversation_id.
    await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(
            object(),
            "flow",
            "Third question",
            "alice",
            previous_response_id=next_chunk["response_id"],
        )
    )
    assert list(await persistence.get_user_conversations("alice")) == ["resp-first"]
    assert calls == [None, "resp-first", "resp-next-alias"]
    assert [m["content"] for m in messages if m["role"] == "user"] == [
        "First question",
        "Follow-up",
        "Third question",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("claim_failure", ["unavailable", "foreign"])
async def test_stream_does_not_expose_unowned_response_id(
    monkeypatch, durable_stream_stores, claim_failure
):
    ownership, persistence, _ = durable_stream_stores
    if claim_failure == "foreign":
        await ownership.claim_session("mallory", "resp-unclaimable")
    else:

        async def unavailable(*_args):
            pass  # Simulate the service's existing logged-but-not-raised DB failure.

        monkeypatch.setattr(ownership, "claim_session", unavailable)

    async def upstream(*_args, **_kwargs):
        yield b'{"id":"resp-unclaimable","delta":{"content":"Not exposed"}}\n'

    monkeypatch.setattr(agent_module, "async_stream", upstream)
    chunks = await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(object(), "flow", "Question", "alice")
    )
    assert len(chunks) == 1
    assert chunks[0]["status"] == "failed"
    assert "id" not in chunks[0] and "response_id" not in chunks[0]
    assert await persistence.get_user_conversations("alice") == {}
    assert await ownership.get_session_owner("resp-unclaimable") == (
        "mallory" if claim_failure == "foreign" else None
    )


@pytest.mark.asyncio
async def test_local_asgi_disconnect_smoke_preserves_followup(durable_stream_stores):
    """Real endpoint → generator → OpenAI SSE adapter → durable stores, locally."""
    _, persistence, _ = durable_stream_stores
    disconnected = anyio.Event()
    upstream_closed = anyio.Event()
    calls = []

    class ProviderStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (
                b"event: response.created\n"
                b'data: {"type":"response.created","response":{"id":"resp-http"}}\n\n'
            )
            yield (
                b"event: response.output_text.delta\n"
                b'data: {"type":"response.output_text.delta","id":"resp-http",'
                b'"delta":{"content":"Partial HTTP answer"}}\n\n'
            )
            await anyio.sleep_forever()

        async def aclose(self):
            upstream_closed.set()

    async def provider(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=ProviderStream()
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b"event: response.output_text.delta\n"
                b'data: {"type":"response.output_text.delta","id":"resp-http-next",'
                b'"delta":{"content":"Follow-up HTTP answer"}}\n\n'
                b"event: response.completed\n"
                b'data: {"type":"response.completed","response":{"id":"resp-http-next",'
                b'"usage":{"input_tokens":3,"output_tokens":4,"total_tokens":7}}}\n\n'
            ),
        )

    async with AsyncOpenAI(
        api_key="local-test-only",
        base_url="https://provider.invalid/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
        max_retries=0,
    ) as client:

        class ChatService:
            async def langflow_chat(self, prompt, _subject, _jwt, **kwargs):
                return agent_module.async_langflow_chat_stream(
                    client,
                    "flow",
                    prompt,
                    kwargs["storage_user_id"],
                    previous_response_id=kwargs["previous_response_id"],
                    conversation_id=kwargs["conversation_id"],
                )

        user = SimpleNamespace(
            user_id="oauth-alice",
            db_user_id="alice",
            jwt_token="local-test-only",
            name="Alice",
            email="alice@example.invalid",
        )
        service = ChatService()
        response = await langflow_endpoint(
            ChatBody(prompt="First HTTP question", stream=True),
            chat_service=service,
            session_manager=None,
            user=user,
        )
        emitted = []

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                chunk = json.loads(message["body"])
                emitted.append(chunk)
                response_id = chunk.get("id") or (chunk.get("response") or {}).get("id")
                if response_id:
                    await _assert_owns(response_id, "alice")
                if chunk.get("delta", {}).get("content"):
                    disconnected.set()

        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}

        # Starlette's real disconnect listener cancels the body iterator using an
        # AnyIO cancel scope, rather than manually throwing into our generator.
        with anyio.fail_after(5):
            await response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send)
        assert upstream_closed.is_set()
        assert len(emitted) == 2
        metadata = await persistence.get_conversation_thread("alice", "resp-http")
        assert metadata["total_messages"] == 2

        followup = await langflow_endpoint(
            ChatBody(
                prompt="Next HTTP question",
                stream=True,
                previous_response_id="resp-http",
                conversation_id="resp-http",
            ),
            chat_service=service,
            session_manager=None,
            user=user,
        )
        chunks = await _collect_error_chunks(followup.body_iterator)
        await _assert_owns("resp-http-next", "alice")
        assert chunks[-1]["response"]["usage"]["total_tokens"] == 7
        assert calls[1]["previous_response_id"] == "resp-http"
        assert [call["input"] for call in calls] == ["First HTTP question", "Next HTTP question"]
        conversations = await persistence.get_user_conversations("alice")
        assert list(conversations) == ["resp-http"]
        assert conversations["resp-http"]["total_messages"] == 4
        messages = agent_module.active_conversations["alice"]["resp-http"]["messages"]
        assert [m["content"] for m in messages if m["role"] != "system"] == [
            "First HTTP question",
            "Partial HTTP answer",
            "Next HTTP question",
            "Follow-up HTTP answer",
        ]
        print(
            "LOCAL SMOKE: disconnect closed upstream; durable ownership accepted "
            "follow-up; 4 messages, 1 conversation, no replay"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("delta", [None, {"content": None}])
async def test_metadata_only_chunk_claims_id_before_exposure(
    monkeypatch, durable_stream_stores, delta
):
    async def upstream(*_args, **_kwargs):
        yield (json.dumps({"id": "resp-metadata", "delta": delta}) + "\n").encode()

    monkeypatch.setattr(agent_module, "async_stream", upstream)
    stream = agent_module.async_langflow_chat_stream(object(), "flow", "Question", "alice")
    chunk = json.loads(await anext(stream))
    await _assert_owns(chunk["id"], "alice")
    await stream.aclose()
