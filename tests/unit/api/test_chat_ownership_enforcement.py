"""Cross-user ownership enforcement on chat endpoints.

Issue: a user could resume another user's conversation by submitting
the other user's `response_id` as `previous_response_id`. This regression
test pins the fix in `src/api/chat.py::_assert_owns`.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.mark.asyncio
async def test_assert_owns_passes_when_session_owned(monkeypatch):
    from api import chat as chat_module
    fake_svc = AsyncMock()
    fake_svc.get_session_owner = AsyncMock(return_value="alice")
    monkeypatch.setattr(
        "services.session_ownership_service.session_ownership_service",
        fake_svc,
    )
    # Same user — no exception
    await chat_module._assert_owns("sess-1", "alice")


@pytest.mark.asyncio
async def test_assert_owns_returns_403_for_other_user(monkeypatch):
    from api import chat as chat_module
    fake_svc = AsyncMock()
    fake_svc.get_session_owner = AsyncMock(return_value="alice")
    monkeypatch.setattr(
        "services.session_ownership_service.session_ownership_service",
        fake_svc,
    )
    with pytest.raises(HTTPException) as exc_info:
        await chat_module._assert_owns("sess-1", "mallory")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {"error": "session_forbidden"}


@pytest.mark.asyncio
async def test_assert_owns_returns_404_for_unknown_session(monkeypatch):
    """Don't leak existence — unknown session is 404 not 403."""
    from api import chat as chat_module
    fake_svc = AsyncMock()
    fake_svc.get_session_owner = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "services.session_ownership_service.session_ownership_service",
        fake_svc,
    )
    with pytest.raises(HTTPException) as exc_info:
        await chat_module._assert_owns("ghost-sess", "alice")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_assert_owns_noop_when_session_id_none():
    """New conversation — no previous_response_id to check."""
    from api import chat as chat_module
    # No monkeypatch needed — should short-circuit before hitting the service
    await chat_module._assert_owns(None, "alice")
    await chat_module._assert_owns("", "alice")


@pytest.mark.asyncio
async def test_chat_endpoint_calls_assert_owns_with_previous_response_id(monkeypatch):
    """Spot-check the wiring: the endpoint must invoke _assert_owns BEFORE
    forwarding to chat_service. Use a sentinel to detect the order."""
    from api import chat as chat_module
    from api.chat import ChatBody

    calls = []

    async def _fake_assert(sid, uid):
        calls.append(("assert", sid, uid))

    fake_chat_service = AsyncMock()
    fake_chat_service.chat = AsyncMock(
        side_effect=lambda *a, **k: calls.append(("chat",)) or "ok"
    )

    monkeypatch.setattr(chat_module, "_assert_owns", _fake_assert)

    class FakeUser:
        user_id = "alice"
        jwt_token = None
        name = "A"
        email = "a@x"

    body = ChatBody(prompt="hi", previous_response_id="sess-1")
    await chat_module.chat_endpoint(
        body=body,
        chat_service=fake_chat_service,
        session_manager=None,
        user=FakeUser(),
    )
    # _assert_owns must run, and must run BEFORE the chat call
    assert calls[0] == ("assert", "sess-1", "alice")


@pytest.mark.asyncio
async def test_chat_endpoint_uses_db_user_id_for_ownership_and_storage(monkeypatch):
    from api import chat as chat_module
    from api.chat import ChatBody

    calls = []

    async def _fake_assert(sid, uid):
        calls.append(("assert", sid, uid))

    fake_chat_service = AsyncMock()
    fake_chat_service.chat = AsyncMock(return_value={"response": "ok"})

    monkeypatch.setattr(chat_module, "_assert_owns", _fake_assert)

    class FakeUser:
        user_id = "oauth-alice"
        db_user_id = "db-alice"
        jwt_token = None
        name = "A"
        email = "a@x"

    body = ChatBody(prompt="hi", previous_response_id="sess-1")
    await chat_module.chat_endpoint(
        body=body,
        chat_service=fake_chat_service,
        session_manager=None,
        user=FakeUser(),
    )
    assert calls[0] == ("assert", "sess-1", "db-alice")
    assert fake_chat_service.chat.await_args.kwargs["storage_user_id"] == "db-alice"
    assert fake_chat_service.chat.await_args.args[1] == "oauth-alice"


@pytest.mark.asyncio
async def test_langflow_endpoint_calls_assert_owns(monkeypatch):
    from api import chat as chat_module
    from api.chat import ChatBody

    calls = []

    async def _fake_assert(sid, uid):
        calls.append(("assert", sid, uid))

    fake_chat_service = AsyncMock()
    fake_chat_service.langflow_chat = AsyncMock(
        side_effect=lambda *a, **k: calls.append(("lc",)) or "ok"
    )

    monkeypatch.setattr(chat_module, "_assert_owns", _fake_assert)

    class FakeUser:
        user_id = "alice"
        jwt_token = None
        name = "A"
        email = "a@x"

    body = ChatBody(prompt="hi", previous_response_id="sess-1")
    await chat_module.langflow_endpoint(
        body=body,
        chat_service=fake_chat_service,
        session_manager=None,
        user=FakeUser(),
    )
    assert calls[0] == ("assert", "sess-1", "alice")


@pytest.mark.asyncio
async def test_delete_session_endpoint_calls_assert_owns(monkeypatch):
    from api import chat as chat_module

    calls = []

    async def _fake_assert(sid, uid):
        calls.append(("assert", sid, uid))

    fake_chat_service = AsyncMock()
    fake_chat_service.delete_session = AsyncMock(return_value={"success": True})

    monkeypatch.setattr(chat_module, "_assert_owns", _fake_assert)

    class FakeUser:
        user_id = "alice"

    await chat_module.delete_session_endpoint(
        session_id="sess-1",
        chat_service=fake_chat_service,
        user=FakeUser(),
    )
    assert calls[0] == ("assert", "sess-1", "alice")


@pytest.mark.asyncio
async def test_upload_context_uses_db_user_id_for_existing_session(monkeypatch):
    from api import upload as upload_module

    calls = []

    async def _fake_assert(sid, uid):
        calls.append(("assert", sid, uid))

    monkeypatch.setattr("api.chat._assert_owns", _fake_assert)

    class FakeFile:
        filename = "notes.txt"

    class FakeUser:
        user_id = "oauth-alice"
        db_user_id = "db-alice"
        jwt_token = "token"
        name = "A"
        email = "a@x"

    fake_document_service = AsyncMock()
    fake_document_service.process_upload_context = AsyncMock(
        return_value={
            "content": "hello",
            "filename": "notes.txt",
            "pages": 1,
            "content_length": 5,
        }
    )
    fake_chat_service = AsyncMock()
    fake_chat_service.upload_context_chat = AsyncMock(return_value=("ok", "resp-1"))

    await upload_module.upload_context(
        file=FakeFile(),
        previous_response_id="sess-1",
        endpoint="chat",
        document_service=fake_document_service,
        chat_service=fake_chat_service,
        session_manager=None,
        user=FakeUser(),
    )

    assert calls[0] == ("assert", "sess-1", "db-alice")
    assert (
        fake_chat_service.upload_context_chat.await_args.kwargs["storage_user_id"]
        == "db-alice"
    )
    assert (
        fake_chat_service.upload_context_chat.await_args.kwargs["user_id"]
        == "oauth-alice"
    )
