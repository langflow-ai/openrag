from unittest.mock import AsyncMock

import pytest

from utils.audit_helpers import write_audit_event_best_effort


class _FakeSession:
    async def commit(self):
        pass


class _FakeSessionContextManager:
    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, *exc_info):
        return False


@pytest.mark.asyncio
async def test_write_audit_event_best_effort_writes_and_commits(monkeypatch):
    write_mock = AsyncMock()
    monkeypatch.setattr("db.repositories.AuditRepo.write", write_mock)
    monkeypatch.setattr("db.engine.SessionLocal", lambda: _FakeSessionContextManager())

    await write_audit_event_best_effort(
        event="test.event",
        actor_user_id="user-1",
        target_type="thing",
        target_id="thing-1",
        audit_metadata={"key": "value"},
    )

    write_mock.assert_awaited_once_with(
        event="test.event",
        actor_user_id="user-1",
        target_type="thing",
        target_id="thing-1",
        audit_metadata={"key": "value"},
    )


@pytest.mark.asyncio
async def test_write_audit_event_best_effort_swallows_exceptions(monkeypatch):
    def boom():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr("db.engine.SessionLocal", boom)

    # Must not raise.
    await write_audit_event_best_effort(event="test.event")


@pytest.mark.asyncio
async def test_write_audit_event_best_effort_swallows_write_failures(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("write failed")

    monkeypatch.setattr("db.repositories.AuditRepo.write", boom)
    monkeypatch.setattr("db.engine.SessionLocal", lambda: _FakeSessionContextManager())

    # Must not raise.
    await write_audit_event_best_effort(event="test.event")
