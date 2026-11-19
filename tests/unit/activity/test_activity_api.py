import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

import api.activity as activity
from db.models import MessageFeedback
from services.activity_cursor import decode_cursor, encode_cursor
from services.activity_service import ActivityService
from tests.unit.activity.conftest import seed

T0 = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def inject_service(factory, monkeypatch):
    """Route handlers get their ActivityService by dependency; call them directly."""
    service = ActivityService(factory)
    for name in ("feedback_list_endpoint", "feedback_summary_endpoint"):
        original = getattr(activity, name)

        async def wrapped(*a, __orig=original, **kw):
            kw.setdefault("activity_service", service)
            return await __orig(*a, **kw)

        monkeypatch.setattr(activity, name, wrapped)


async def drain(handler, **kw):
    seen, cursor = [], None
    while True:
        resp = await handler(cursor=cursor, **kw)
        body = json.loads(resp.body)
        seen += [i["id"] for i in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            return seen


BASE = dict(start=None, end=None, event=None, actor_user_id=None, limit=7, _user=None)


def test_cursor_validation():
    f = {"k": "audit", "ev": "a"}
    c = encode_cursor(T0, "id1", T0, f)
    assert decode_cursor(c, f).id == "id1"
    for bad in ("not-a-cursor", "e30"):
        with pytest.raises(HTTPException) as e:
            decode_cursor(bad, f)
        assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        decode_cursor(c, {"k": "audit", "ev": "b"})
    assert e.value.status_code == 422


@pytest.mark.asyncio
async def test_inverted_range_rejected(factory):
    with pytest.raises(HTTPException) as e:
        await activity.feedback_summary_endpoint(start=T0, end=T0, rating=None, _user=None)
    assert e.value.status_code == 422


async def feedback_rows(factory, ups, downs):
    await seed(factory)
    async with factory() as s:
        for i in range(ups + downs):
            s.add(
                MessageFeedback(
                    id=f"f{i:03d}",
                    message_id="ma",
                    user_id="alice" if i == 0 else f"u{i}",
                    rating="up" if i < ups else "down",
                    comment="=cmd()" if i == 0 else None,
                    created_at=T0 + timedelta(minutes=i % 3),
                    updated_at=T0,
                )
            )
        await s.commit()


@pytest.mark.asyncio
async def test_feedback_summary_and_empty_denominator(factory):
    await seed(factory)
    empty = json.loads(
        (
            await activity.feedback_summary_endpoint(start=None, end=None, rating=None, _user=None)
        ).body
    )
    assert empty["total"] == 0 and empty["positive_percentage"] is None
    await feedback_rows_fk(factory)


async def feedback_rows_fk(factory):
    from db.models import User

    async with factory() as s:
        for i in range(1, 4):
            s.add(User(id=f"u{i}", oauth_provider="t", oauth_subject=f"u{i}"))
        await s.flush()
        for i, r in enumerate(["up", "up", "down"], start=1):
            s.add(
                MessageFeedback(
                    id=f"g{i}",
                    message_id="ma",
                    user_id=f"u{i}",
                    rating=r,
                    created_at=T0 + timedelta(days=i),
                    updated_at=T0,
                )
            )
        await s.commit()
    body = json.loads(
        (
            await activity.feedback_summary_endpoint(start=None, end=None, rating=None, _user=None)
        ).body
    )
    assert (body["up"], body["down"], body["total"], body["positive_percentage"]) == (2, 1, 3, 66.7)
    ranged = json.loads(
        (
            await activity.feedback_summary_endpoint(
                start=T0 + timedelta(days=2), end=T0 + timedelta(days=4), rating=None, _user=None
            )
        ).body
    )
    assert ranged["total"] == 2
    down = json.loads(
        (
            await activity.feedback_summary_endpoint(
                start=None, end=None, rating="down", _user=None
            )
        ).body
    )
    assert (down["up"], down["down"]) == (0, 1)


@pytest.mark.asyncio
async def test_feedback_list_dto_has_no_content(factory):
    await seed(factory)
    await feedback_rows_fk(factory)
    body = json.loads(
        (
            await activity.feedback_list_endpoint(
                start=None, end=None, rating=None, limit=2, cursor=None, _user=None
            )
        ).body
    )
    item = body["items"][0]
    assert "content" not in item and "prompt" not in item and item["conversation_id"] == "c1"
    assert body["next_cursor"]
    ids = await drain(
        activity.feedback_list_endpoint, start=None, end=None, rating=None, limit=2, _user=None
    )
    assert sorted(ids) == ["g1", "g2", "g3"] and len(ids) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("rbac,noauth", [(False, False), (True, True)])
async def test_admin_gate_denies_when_rbac_off_or_noauth(monkeypatch, rbac, noauth):
    import config.settings as settings
    import services.rbac_service as rbac_service

    monkeypatch.setattr(rbac_service, "is_rbac_enforced", lambda: rbac)
    monkeypatch.setattr(settings, "is_no_auth_mode", lambda: noauth)
    with pytest.raises(HTTPException) as e:
        await activity.require_activity_admin(request=None, user=None, rbac=None)
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_gate_honours_permission_grants(monkeypatch):
    from types import SimpleNamespace

    import config.settings as settings
    import services.rbac_service as rbac_service

    monkeypatch.setattr(rbac_service, "is_rbac_enforced", lambda: True)
    monkeypatch.setattr(settings, "is_no_auth_mode", lambda: False)
    seen = {}

    async def fake_enforce(request, user, rbac, perm):
        seen["perm"] = perm
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(activity, "enforce_permission", fake_enforce)
    with pytest.raises(HTTPException):
        await activity.require_activity_admin(request=SimpleNamespace(), user=None, rbac=None)
    assert seen["perm"] == "audit:read"


@pytest.mark.asyncio
async def test_v1_feedback_route_returns_503_when_db_storage_is_unavailable(monkeypatch):
    from types import SimpleNamespace

    import api.v1.chat as v1_chat

    monkeypatch.setattr("api.chat.db_writes_enabled", lambda: False)
    called = []

    async def submit(**kw):
        called.append(kw)

    resp = await v1_chat.chat_feedback_endpoint(
        chat_id="c1",
        message_id="m1",
        body=SimpleNamespace(rating="up", comment=None),
        feedback_service=SimpleNamespace(submit=submit),
        user=SimpleNamespace(user_id="u", db_user_id="u"),
    )
    assert resp.status_code == 503
    assert called == []
