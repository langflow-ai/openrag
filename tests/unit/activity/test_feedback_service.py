import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from db.models import ChatMessage, MessageFeedback
from db.repositories import ChatHistoryRepo, FeedbackRepo
from services.feedback_service import FeedbackService
from services.native_chat_history_service import NativeChatHistoryService
from tests.unit.activity.conftest import seed


async def submit(factory, **kw):
    args = dict(user_id="alice", conversation_id="c1", message_id="ma", rating="up", comment=None)
    args.update(kw)
    return await FeedbackService(factory).submit(**args)


@pytest.mark.asyncio
async def test_submit_persists_and_survives_fresh_session(factory):
    await seed(factory)
    saved = await submit(factory, comment="nice")
    assert saved["rating"] == "up" and saved["comment"] == "nice"
    async with factory() as s:
        row = await FeedbackRepo(s).get("alice", "ma")
        assert row.model == "m1" and row.retrieval == {"document_ids": ["d1"], "chunk_ids": ["k1"]}


@pytest.mark.asyncio
async def test_identical_submission_is_noop_and_change_advances_updated_at(factory):
    await seed(factory)
    first = await submit(factory, comment="x")
    again = await submit(factory, comment="x")
    assert again == first
    changed = await submit(factory, rating="down", comment="x")
    assert changed["created_at"] == first["created_at"]
    assert changed["updated_at"] > first["updated_at"]
    assert changed["rating"] == "down"
    cleared = await submit(factory, rating="down", comment=None)
    assert cleared["comment"] is None


@pytest.mark.asyncio
async def test_concurrent_upserts_yield_single_row(factory):
    await seed(factory)
    await asyncio.gather(*(submit(factory, rating="up" if i % 2 else "down") for i in range(8)))
    async with factory() as s:
        rows = (await s.execute(select(MessageFeedback))).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kw,status",
    [
        ({"user_id": "bob"}, 403),
        ({"conversation_id": "c2"}, 404),  # message ma is not in c2: spoofing
        ({"conversation_id": "nope"}, 404),
        ({"message_id": "mu"}, 404 if False else 422),  # user message
        ({"message_id": "missing"}, 404),
        ({"rating": "meh"}, 422),
        ({"comment": "x" * 2001}, 422),
    ],
)
async def test_rejections(factory, kw, status):
    await seed(factory)
    with pytest.raises(HTTPException) as exc:
        await submit(factory, **kw)
    assert exc.value.status_code == status
    async with factory() as s:
        assert (await s.execute(select(MessageFeedback))).first() is None


@pytest.mark.asyncio
async def test_error_and_legacy_messages_rejected(factory):
    await seed(factory, provenance=False)
    with pytest.raises(HTTPException) as exc:
        await submit(factory)
    assert exc.value.status_code == 422
    async with factory() as s:
        await s.execute(text("update chat_messages set error=1, event_data=NULL where id='ma'"))
        await s.commit()
    with pytest.raises(HTTPException):
        await submit(factory)


@pytest.mark.asyncio
async def test_rollback_on_failure(factory, monkeypatch):
    await seed(factory)

    async def boom(self, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(FeedbackRepo, "upsert", boom)
    with pytest.raises(RuntimeError):
        await submit(factory)
    async with factory() as s:
        assert (await s.execute(select(MessageFeedback))).first() is None


@pytest.mark.asyncio
async def test_history_exposes_ids_and_only_callers_feedback(factory):
    await seed(factory)
    await submit(factory, comment="mine")
    async with factory() as s:
        from db.models import User  # noqa: F401
    svc = NativeChatHistoryService(factory)
    msgs = await svc.messages_for("c1", "alice")
    assistant = [m for m in msgs if m["role"] == "assistant"][0]
    assert assistant["message_id"] == "ma"
    assert assistant["feedback"]["rating"] == "up"
    assert "message_id" not in [m for m in msgs if m["role"] == "user"][0]
    # another viewer of the same rows never sees alice's feedback
    rows = await ChatHistoryRepo(factory()).list_messages("c1") if False else None
    async with factory() as s:
        rows = await ChatHistoryRepo(s).list_messages("c1")
        other = NativeChatHistoryService._message_payload(
            rows, await FeedbackRepo(s).for_user_messages("bob", ["ma"])
        )
    assert "feedback" not in [m for m in other if m["role"] == "assistant"][0]


@pytest.mark.asyncio
async def test_append_returns_committed_id(factory):
    await seed(factory)
    mid = await NativeChatHistoryService(factory).append("c1", "alice", "assistant", content="n")
    async with factory() as s:
        assert (await s.get(ChatMessage, mid)).content == "n"


@pytest.mark.asyncio
async def test_conversation_delete_removes_feedback_with_and_without_fk_enforcement(
    factory_fk_modes,
):
    factory = factory_fk_modes
    await seed(factory)
    await submit(factory)
    async with factory() as s:
        assert await ChatHistoryRepo(s).delete_conversation("c1", "alice")
        await s.commit()
        assert (await s.execute(select(MessageFeedback))).first() is None


@pytest.mark.asyncio
async def test_user_delete_cascades_feedback_when_fk_enforced(factory):
    # Needs enforced foreign keys (PostgreSQL always; SQLite only when enabled).
    await seed(factory)
    await seed_again(factory)


async def seed_again(factory):
    async with factory() as s:
        from db.models import ChatConversation

        s.add(ChatConversation(id="c9", user_id="alice"))
        await s.flush()
        s.add(
            ChatMessage(
                id="m9",
                conversation_id="c9",
                sequence=0,
                role="assistant",
                content="a",
                event_data={"provenance": {}},
            )
        )
        await s.commit()
    await FeedbackService(factory).submit(
        user_id="alice", conversation_id="c9", message_id="m9", rating="up", comment=None
    )
    async with factory() as s:
        await s.execute(text("delete from users where id='alice'"))  # FK ON DELETE CASCADE
        await s.commit()
        assert (await s.execute(select(MessageFeedback))).first() is None


@pytest.mark.asyncio
async def test_db_constraints(factory):
    await seed(factory)
    from sqlalchemy.exc import IntegrityError

    async with factory() as s:
        s.add(MessageFeedback(id="f", message_id="ma", user_id="alice", rating="sideways"))
        with pytest.raises(IntegrityError):
            await s.commit()


@pytest.mark.asyncio
async def test_delete_stale_removes_feedback_only_for_expired_conversations(factory_fk_modes):
    factory = factory_fk_modes
    from datetime import UTC, datetime, timedelta

    from db.models import ChatConversation

    await seed(factory)
    await submit(factory)  # feedback on c1/ma
    async with factory() as s:
        old = datetime.now(UTC) - timedelta(days=30)
        (await s.get(ChatConversation, "c1")).last_activity = old
        await s.commit()
    async with factory() as s:
        # c2 is fresh and has feedback that must survive the prune.
        await FeedbackRepo(s).upsert(
            user_id="alice",
            message_id="mo",
            rating="down",
            comment=None,
            model_provider=None,
            model="m",
            retrieval=None,
        )
        await s.commit()
    async with factory() as s:
        assert await ChatHistoryRepo(s).delete_stale(7) == 1
        await s.commit()
    async with factory() as s:
        remaining = (await s.execute(select(MessageFeedback))).scalars().all()
        assert [f.message_id for f in remaining] == ["mo"]
        assert await s.get(ChatMessage, "ma") is None
        assert await s.get(ChatMessage, "mo") is not None


@pytest.mark.asyncio
async def test_feedback_timestamps_round_trip_as_aware_utc(factory):
    await seed(factory)
    await submit(factory)
    async with factory() as s:
        row = await FeedbackRepo(s).get("alice", "ma")
        assert row.created_at.tzinfo is not None
        assert row.created_at.utcoffset().total_seconds() == 0


@pytest.mark.asyncio
async def test_feedback_is_not_written_for_a_message_deleted_after_validation(factory_fk_modes):
    """INSERT ... WHERE EXISTS: no orphan row even with SQLite FKs off."""
    from db.repositories.feedback_repo import MessageGoneError

    factory = factory_fk_modes
    await seed(factory)
    async with factory() as s:
        await s.execute(text("delete from chat_messages where id='ma'"))
        await s.commit()
    async with factory() as s:
        with pytest.raises(MessageGoneError):
            await FeedbackRepo(s).upsert(
                user_id="alice",
                message_id="ma",
                rating="up",
                comment=None,
                model_provider=None,
                model="m",
                retrieval=None,
            )
        await s.rollback()
        assert (await s.execute(select(MessageFeedback))).first() is None


@pytest.mark.asyncio
async def test_service_maps_a_vanished_message_to_404(factory, monkeypatch):
    await seed(factory)

    async def gone(self, **kw):
        from db.repositories.feedback_repo import MessageGoneError

        raise MessageGoneError(kw["message_id"])

    monkeypatch.setattr(FeedbackRepo, "upsert", gone)
    with pytest.raises(HTTPException) as exc:
        await submit(factory)
    assert exc.value.status_code == 404
