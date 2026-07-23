"""VULN-13906: async_response_stream must audit detected tool calls, best-effort."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent import async_response_stream


class Chunk(SimpleNamespace):
    def model_dump(self, exclude=None):
        data = dict(self.__dict__)
        for key in exclude or ():
            data.pop(key, None)
        return data


class AsyncChunkStream:
    def __init__(self, chunks):
        self._chunks = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration from None


class FakeResponses:
    def __init__(self, chunks):
        self._chunks = chunks

    async def create(self, **kwargs):
        return AsyncChunkStream(self._chunks)


class FakeClient:
    default_headers: dict[str, str] = {}
    api_key = "test-key"

    def __init__(self, chunks):
        self.responses = FakeResponses(chunks)


@pytest.mark.asyncio
async def test_detected_tool_call_triggers_audit_write(monkeypatch):
    audit_mock = AsyncMock()
    monkeypatch.setattr("agent.write_audit_event_best_effort", audit_mock)
    monkeypatch.setattr("auth_context.get_current_user_id", lambda: "user-42")

    chunks = [
        Chunk(
            type="response.output_item.delta",
            results=[{"text": "some retrieved chunk", "filename": "doc.txt"}],
        ),
    ]
    client = FakeClient(chunks)

    collected = []
    async for event in async_response_stream(client, "hello", "flow-id"):
        collected.append(json.loads(event.decode("utf-8")))

    audit_mock.assert_awaited_once()
    call_kwargs = audit_mock.call_args.kwargs
    assert call_kwargs["event"] == "agent.tool_call"
    assert call_kwargs["actor_user_id"] == "user-42"
    assert call_kwargs["audit_metadata"]["result_count"] == 1
    # The raw retrieved text must never appear in the audit metadata.
    assert "some retrieved chunk" not in json.dumps(call_kwargs["audit_metadata"])

    # Streaming behavior is unaffected: a synthetic tool-call event is still injected.
    assert any(e.get("item", {}).get("type") == "retrieval_call" for e in collected)


@pytest.mark.asyncio
async def test_audit_write_failure_does_not_break_streaming(monkeypatch):
    """The audit call is best-effort inside write_audit_event_best_effort itself —
    verify a raising AuditRepo.write still lets the stream complete normally."""

    async def boom(**kwargs):
        raise RuntimeError("audit db is down")

    monkeypatch.setattr("db.repositories.AuditRepo.write", boom)
    monkeypatch.setattr(
        "db.engine.SessionLocal",
        lambda: _FakeSessionContextManager(),
    )

    chunks = [
        Chunk(
            type="response.output_item.delta",
            results=[{"text": "retrieved", "filename": "doc.txt"}],
        ),
    ]
    client = FakeClient(chunks)

    collected = []
    async for event in async_response_stream(client, "hello", "flow-id"):
        collected.append(json.loads(event.decode("utf-8")))

    assert any(e.get("item", {}).get("type") == "retrieval_call" for e in collected)


class _FakeSession:
    async def commit(self):
        pass


class _FakeSessionContextManager:
    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, *exc_info):
        return False
