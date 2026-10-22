"""Durable chat ownership, continuation, cancellation, and deletion regressions."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
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
from api.chat import ChatBody, _assert_owns, delete_session_endpoint, langflow_endpoint
from services.chat_service import ChatService
from services.conversation_persistence_service import ConversationPersistenceService
from services.session_ownership_service import SessionOwnershipService


async def _collect_error_chunks(stream) -> list[dict]:
    return [json.loads(raw.decode("utf-8")) async for raw in stream]


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

        async def unavailable(*_args, **_kwargs):
            return False

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
async def test_local_asgi_disconnect_smoke_preserves_followup(monkeypatch, durable_stream_stores):
    """Real endpoint → generator → OpenAI SSE adapter → durable stores, locally."""
    _, persistence, factory = durable_stream_stores
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

        class EndpointChatService:
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
        service = EndpointChatService()
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

        # Restart before canonical deletion: aliases must come from durable state.
        reloaded = SessionOwnershipService(session_factory=factory)
        monkeypatch.setattr(
            "services.session_ownership_service.session_ownership_service", reloaded
        )
        monkeypatch.setattr(agent_module, "active_conversations", {})
        upstream_deletes = []

        async def monitor_delete(method, path):
            assert method == "DELETE"
            upstream_deletes.append(path.rsplit("/", 1)[-1])
            return httpx.Response(204)

        monkeypatch.setattr("services.chat_service.clients.langflow_request", monitor_delete)
        deletion = await delete_session_endpoint(
            session_id="resp-http", chat_service=ChatService(), user=user
        )
        assert deletion.status_code == 200
        assert set(upstream_deletes) == {"resp-http", "resp-http-next"}
        fresh = SessionOwnershipService(session_factory=factory)
        monkeypatch.setattr("services.session_ownership_service.session_ownership_service", fresh)
        with pytest.raises(HTTPException) as missing:
            await langflow_endpoint(
                ChatBody(
                    prompt="Cannot resurrect", stream=True, previous_response_id="resp-http-next"
                ),
                chat_service=service,
                session_manager=None,
                user=user,
            )
        assert missing.value.status_code == 404
        assert len(calls) == 2

        # Actual endpoint + SSE adapter with both persistent destinations broken.
        ownership_path = Path(fresh.ownership_file)
        if ownership_path.exists():
            ownership_path.unlink()
        ownership_path.mkdir()

        def unavailable_database():
            raise OSError("local smoke database unavailable")

        monkeypatch.setattr(fresh, "_resolve_session_factory", lambda: unavailable_database)
        failed = await langflow_endpoint(
            ChatBody(prompt="Fail closed", stream=True),
            chat_service=service,
            session_manager=None,
            user=user,
        )
        failed_chunks = await _collect_error_chunks(failed.body_iterator)
        assert len(failed_chunks) == 1 and failed_chunks[0]["status"] == "failed"
        assert "id" not in failed_chunks[0] and "response_id" not in failed_chunks[0]
        assert (
            await SessionOwnershipService(session_factory=factory).get_session_owner(
                "resp-http-next"
            )
            is None
        )
        print(
            "LOCAL SMOKE: disconnect/follow-up retained 4 messages; restart + "
            "canonical deletion removed both upstream sessions and alias authorization; "
            "persistent failures emitted no client ID"
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


@pytest.mark.asyncio
@pytest.mark.parametrize("delete_id", ["resp-first", "resp-second"])
async def test_delete_canonical_revokes_aliases_after_reload(
    monkeypatch, durable_stream_stores, delete_id
):
    ownership, persistence, factory = durable_stream_stores

    async def upstream(*_args, **kwargs):
        response_id = "resp-second" if kwargs.get("previous_response_id") else "resp-first"
        yield (json.dumps({"id": response_id, "delta": {"content": "Answer"}}) + "\n").encode()

    monkeypatch.setattr(agent_module, "async_stream", upstream)
    for previous in (None, "resp-first"):
        await _collect_error_chunks(
            agent_module.async_langflow_chat_stream(
                object(), "flow", "Question", "alice", previous_response_id=previous
            )
        )
    await ownership.claim_session("mallory", "resp-foreign")
    await ownership.claim_session("alice", "resp-unrelated")
    assert list(await persistence.get_user_conversations("alice")) == ["resp-first"]
    assert await agent_module.delete_user_conversation("mallory", "resp-first") is False
    assert agent_module.active_conversations["alice"]["resp-first"]["messages"]
    # Restart: neither ownership cache nor the in-memory response_ids can help.
    reloaded = SessionOwnershipService(session_factory=factory)
    monkeypatch.setattr("services.session_ownership_service.session_ownership_service", reloaded)
    monkeypatch.setattr(agent_module, "active_conversations", {})
    persistence = ConversationPersistenceService(
        storage_file=persistence.storage_file, session_factory=factory
    )
    monkeypatch.setattr(agent_module, "conversation_persistence", persistence)
    assert await agent_module.delete_user_conversation("alice", delete_id) is True
    fresh = SessionOwnershipService(session_factory=factory)
    monkeypatch.setattr("services.session_ownership_service.session_ownership_service", fresh)
    for response_id in ("resp-first", "resp-second"):
        with pytest.raises(HTTPException) as missing:
            await _assert_owns(response_id, "alice")
        assert missing.value.status_code == 404
    assert await fresh.get_session_owner("resp-foreign") == "mallory"
    assert await fresh.get_session_owner("resp-unrelated") == "alice"
    assert await persistence.get_user_conversations("alice") == {}


@pytest.mark.asyncio
async def test_persistent_claim_failure_never_exposes_cached_id(monkeypatch, durable_stream_stores):
    ownership, persistence, factory = durable_stream_stores
    # A real IO failure, not a stubbed claim: cache echo must not prove durability.
    Path(ownership.ownership_file).mkdir()

    def unavailable_database():
        raise OSError("local database unavailable")

    monkeypatch.setattr(ownership, "_resolve_session_factory", lambda: unavailable_database)

    async def upstream(*_args, **_kwargs):
        yield b'{"id":"resp-file-failure","delta":{"content":"Not exposed"}}\n'

    monkeypatch.setattr(agent_module, "async_stream", upstream)
    chunks = await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(object(), "flow", "Question", "alice")
    )
    assert len(chunks) == 1
    assert chunks[0]["status"] == "failed"
    assert "id" not in chunks[0] and "response_id" not in chunks[0]
    assert await ownership.get_session_owner("resp-file-failure") is None
    assert (
        await SessionOwnershipService(session_factory=factory).get_session_owner(
            "resp-file-failure"
        )
        is None
    )
    assert await persistence.get_user_conversations("alice") == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("durable_stream_stores", ["hybrid", "files"], indirect=True)
async def test_failed_file_revocation_is_not_reported_as_success(
    monkeypatch, durable_stream_stores
):
    ownership, _, _ = durable_stream_stores

    async def upstream(*_args, **_kwargs):
        yield b'{"id":"resp-delete-failure","delta":{"content":"Answer"}}\n'

    monkeypatch.setattr(agent_module, "async_stream", upstream)
    await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(object(), "flow", "Question", "alice")
    )
    ownership_path = Path(ownership.ownership_file)
    ownership_path.unlink()
    ownership_path.mkdir()

    async def monitor_delete(_self, _session_id):
        return True

    monkeypatch.setattr(ChatService, "_delete_langflow_session", monitor_delete)
    result = await ChatService().delete_session("alice", "resp-delete-failure")
    assert result["success"] is False
    await _assert_owns("resp-delete-failure", "alice")
    assert "resp-delete-failure" in agent_module.active_conversations["alice"]


@pytest.mark.asyncio
@pytest.mark.parametrize("durable_stream_stores", ["hybrid"], indirect=True)
async def test_json_only_alias_cleanup_precedes_failed_db_revocation(
    monkeypatch, durable_stream_stores
):
    from db.repositories import SessionOwnershipRepo

    ownership, _, factory = durable_stream_stores

    async def upstream(*_args, **kwargs):
        response_id = "alias" if kwargs.get("previous_response_id") else "canonical"
        yield (json.dumps({"id": response_id, "delta": {"content": "Answer"}}) + "\n").encode()

    monkeypatch.setattr(agent_module, "async_stream", upstream)
    await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(object(), "flow", "First", "alice")
    )

    def unavailable_database():
        raise OSError("database temporarily unavailable")

    ownership._session_factory = unavailable_database
    await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(
            object(), "flow", "Next", "alice", previous_response_id="canonical"
        )
    )
    ownership._session_factory = factory
    async with factory() as session:
        assert await SessionOwnershipRepo(session).get("alias") is None
    assert await ownership.get_session_owner("alias") == "alice"
    original = SessionOwnershipRepo.release

    async def failed_release(*_args):
        raise OSError("database revocation failed")

    upstream_deletes = []

    async def monitor_delete(_self, session_id):
        upstream_deletes.append(session_id)
        return True

    monkeypatch.setattr(ChatService, "_delete_langflow_session", monitor_delete)
    monkeypatch.setattr(SessionOwnershipRepo, "release", failed_release)
    result = await ChatService().delete_session("alice", "canonical")
    assert result["success"] is False
    assert set(upstream_deletes) == {"canonical", "alias"}
    # Even though JSON-only ownership was revoked, its upstream cleanup was not
    # lost. The surviving canonical DB row can be retried after a restart.
    reloaded = SessionOwnershipService(session_factory=factory)
    monkeypatch.setattr("services.session_ownership_service.session_ownership_service", reloaded)
    monkeypatch.setattr(SessionOwnershipRepo, "release", original)
    assert (await ChatService().delete_session("alice", "canonical"))["success"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("storage", ["persisted", "memory"])
@pytest.mark.parametrize("operation", ["direct", "single", "bulk"])
async def test_delete_own_orphan_without_upstream_authorization(
    monkeypatch, durable_stream_stores, storage, operation
):
    ownership, persistence, _ = durable_stream_stores
    state = {"messages": [], "created_at": datetime.now()}
    if storage == "persisted":
        await persistence.store_conversation_thread("alice", "orphan", state)
    else:
        agent_module.active_conversations["alice"] = {"orphan": state}
    assert await ownership.get_session_owner("orphan") is None
    upstream_deletes = []

    async def monitor_delete(_self, session_id):
        upstream_deletes.append(session_id)
        return True

    monkeypatch.setattr(ChatService, "_delete_langflow_session", monitor_delete)
    if operation == "direct":
        assert await agent_module.delete_user_conversation("alice", "orphan") is True
    elif operation == "single":
        assert (await ChatService().delete_session("alice", "orphan"))["success"] is True
    else:
        assert await ChatService().delete_sessions("alice", ["orphan"]) == {
            "deleted": ["orphan"],
            "failed": [],
        }
    assert await persistence.get_conversation_thread("alice", "orphan") == {}
    assert "orphan" not in agent_module.active_conversations.get("alice", {})
    assert upstream_deletes == []
    with pytest.raises(HTTPException) as missing:
        await _assert_owns("orphan", "alice")
    assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_all_removes_persisted_orphans_only_for_caller(
    monkeypatch, durable_stream_stores
):
    _, persistence, _ = durable_stream_stores
    state = {"messages": [], "created_at": datetime.now()}
    await persistence.store_conversation_thread("alice", "orphan", state)
    await persistence.store_conversation_thread("mallory", "foreign", state)
    upstream_deletes = []

    async def monitor_delete(_self, session_id):
        upstream_deletes.append(session_id)
        return True

    monkeypatch.setattr(ChatService, "_delete_langflow_session", monitor_delete)
    assert await ChatService().delete_all_user_sessions("alice") == {
        "success": True,
        "deleted_count": 1,
        "total_count": 1,
    }
    assert await persistence.get_user_conversations("alice") == {}
    assert await persistence.get_conversation_thread("mallory", "foreign")
    assert upstream_deletes == []


@pytest.mark.asyncio
async def test_missing_and_foreign_deletes_never_touch_upstream(monkeypatch, durable_stream_stores):
    ownership, persistence, _ = durable_stream_stores
    state = {"messages": [], "created_at": datetime.now()}
    await persistence.store_conversation_thread("mallory", "foreign", state)
    await ownership.claim_session("mallory", "foreign")
    upstream_deletes = []

    async def monitor_delete(_self, session_id):
        upstream_deletes.append(session_id)
        return True

    monkeypatch.setattr(ChatService, "_delete_langflow_session", monitor_delete)
    service = ChatService()
    for session_id in ("missing", "foreign"):
        assert await agent_module.delete_user_conversation("alice", session_id) is False
        assert (await service.delete_session("alice", session_id))["not_found"] is True
    assert await service.delete_sessions("alice", ["missing", "foreign"]) == {
        "deleted": [],
        "failed": ["missing", "foreign"],
    }
    assert await persistence.get_conversation_thread("mallory", "foreign")
    assert await ownership.get_session_owner("foreign") == "mallory"
    assert upstream_deletes == []
    user = SimpleNamespace(db_user_id="alice", user_id="oauth-alice")
    for session_id, status in (("missing", 404), ("foreign", 403)):
        with pytest.raises(HTTPException) as denied:
            await delete_session_endpoint(session_id=session_id, chat_service=service, user=user)
        assert denied.value.status_code == status


@pytest.mark.asyncio
async def test_delete_uses_one_owned_snapshot_for_upstream_and_revocation(
    monkeypatch, durable_stream_stores
):
    ownership, _, _ = durable_stream_stores

    async def upstream(*_args, **_kwargs):
        yield b'{"id":"canonical","response_id":"alias","delta":{"content":"Answer"}}\n'

    monkeypatch.setattr(agent_module, "async_stream", upstream)
    await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(object(), "flow", "Question", "alice")
    )
    resolve = ownership.get_conversation_sessions
    resolutions = []

    async def resolve_once(user_id, session_id):
        resolutions.append(session_id)
        assert len(resolutions) == 1, "Deletion resolved a different ownership snapshot"
        return await resolve(user_id, session_id)

    upstream_deletes = []

    async def monitor_delete(_self, session_id):
        upstream_deletes.append(session_id)
        if session_id == "canonical":
            assert await ownership.claim_session("alice", "late-alias", "canonical")
        return True

    monkeypatch.setattr(ownership, "get_conversation_sessions", resolve_once)
    monkeypatch.setattr(ChatService, "_delete_langflow_session", monitor_delete)
    result = await ChatService().delete_session("alice", "alias")
    assert result["success"] is True
    assert resolutions == ["alias"]
    assert set(upstream_deletes) == {"canonical", "alias"}
    assert await ownership.get_session_owner("canonical") is None
    assert await ownership.get_session_owner("alias") is None
    # A claim arriving after the snapshot is not revoked without upstream cleanup.
    assert await ownership.get_session_owner("late-alias") == "alice"


@pytest.mark.asyncio
async def test_restart_alias_only_continuation_keeps_durable_canonical(
    monkeypatch, durable_stream_stores
):
    _, persistence, factory = durable_stream_stores
    calls = []

    async def upstream(*_args, **kwargs):
        calls.append(kwargs.get("previous_response_id"))
        response_id = ("canonical", "alias", "after-restart")[len(calls) - 1]
        yield (json.dumps({"id": response_id, "delta": {"content": "Answer"}}) + "\n").encode()

    monkeypatch.setattr(agent_module, "async_stream", upstream)
    for previous in (None, "canonical"):
        await _collect_error_chunks(
            agent_module.async_langflow_chat_stream(
                object(),
                "flow",
                "First question" if previous is None else "Follow-up",
                "alice",
                previous_response_id=previous,
                filter_id="knowledge-filter" if previous is None else None,
            )
        )
    before_restart = await persistence.get_conversation_thread("alice", "canonical")
    assert before_restart["total_messages"] == 4
    reloaded = SessionOwnershipService(session_factory=factory)
    monkeypatch.setattr("services.session_ownership_service.session_ownership_service", reloaded)
    monkeypatch.setattr(agent_module, "active_conversations", {})
    reloaded_persistence = ConversationPersistenceService(
        storage_file=persistence.storage_file, session_factory=factory
    )
    monkeypatch.setattr(agent_module, "conversation_persistence", reloaded_persistence)
    await _assert_owns("alias", "alice")
    await _collect_error_chunks(
        agent_module.async_langflow_chat_stream(
            object(), "flow", "After restart", "alice", previous_response_id="alias"
        )
    )
    assert calls == [None, "canonical", "alias"]
    assert list(await reloaded_persistence.get_user_conversations("alice")) == ["canonical"]
    after_restart = await reloaded_persistence.get_conversation_thread("alice", "canonical")
    assert after_restart["title"] == before_restart["title"] == "First question"
    assert after_restart["created_at"] == before_restart["created_at"]
    assert after_restart["filter_id"] == "knowledge-filter"
    assert after_restart["total_messages"] == 6
    fresh = SessionOwnershipService(session_factory=factory)
    assert set(await fresh.get_conversation_sessions("alice", "after-restart")) == {
        "canonical",
        "alias",
        "after-restart",
    }
    assert set(agent_module.active_conversations["alice"]) == {"canonical"}
