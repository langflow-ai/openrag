"""migrations_runtime.run — legacy users discovered from JSON files."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.migrations_runtime import RuntimeMigrationError, run as run_migration  # noqa: E402
from db.models import MigrationStatus, User as UserRow  # noqa: E402


@pytest_asyncio.fixture
async def session_in_temp_data():
    with tempfile.TemporaryDirectory() as data_dir:
        os.environ["OPENRAG_DATA_PATH"] = data_dir
        Path(data_dir, "connections.json").write_text(
            json.dumps(
                {
                    "connections": [
                        {"connection_id": "x1", "user_id": "user-aaa", "config": {}},
                        {"connection_id": "x2", "user_id": "user-bbb", "config": {}},
                        {"connection_id": "x3", "user_id": "user-aaa", "config": {}},
                    ]
                }
            )
        )
        Path(data_dir, "conversations.json").write_text(
            json.dumps({"user-bbb": {}, "user-ccc": {}})
        )
        Path(data_dir, "session_ownership.json").write_text(
            json.dumps({"sess1": {"user_id": "user-ddd"}})
        )

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        async with SessionLocal() as s:
            yield s
        await engine.dispose()
        del os.environ["OPENRAG_DATA_PATH"]


@pytest.mark.asyncio
async def test_legacy_users_are_inserted(session_in_temp_data):
    s = session_in_temp_data
    await run_migration(s)
    await s.commit()

    rows = (await s.execute(select(UserRow))).scalars().all()
    legacy_ids = {r.oauth_subject for r in rows if r.oauth_provider == "legacy"}
    assert legacy_ids == {"user-aaa", "user-bbb", "user-ccc", "user-ddd"}

    status = await s.get(MigrationStatus, "json_to_db_v1")
    assert status is not None


@pytest.mark.asyncio
async def test_idempotent_second_run(session_in_temp_data):
    s = session_in_temp_data
    await run_migration(s)
    await s.commit()
    count_before = len((await s.execute(select(UserRow))).scalars().all())

    await run_migration(s)
    await s.commit()
    count_after = len((await s.execute(select(UserRow))).scalars().all())

    assert count_before == count_after


@pytest.mark.asyncio
async def test_partial_collision_keeps_other_legacy_inserts(session_in_temp_data):
    """If one legacy user_id already exists in the DB (e.g. from a prior
    run on a different file), the per-row IntegrityError must roll back
    only THAT savepoint, not the whole outer transaction. Previously
    `session.rollback()` in the except dropped every other newly-flushed
    row in the same migration pass.
    """
    s = session_in_temp_data
    from db.migrations_runtime import migrate_legacy_users
    from db.repositories._helpers import email_lookup_hash

    # Seed: pre-existing legacy row for user-aaa (one of the four ids
    # that the JSON fixtures will try to insert).
    pre_existing = UserRow(
        id="user-aaa",
        oauth_provider="legacy",
        oauth_subject="user-aaa",
        email="user-aaa@unknown.local",
        email_lookup_hash=email_lookup_hash("user-aaa@unknown.local"),
        display_name="user-aaa",
    )
    s.add(pre_existing)
    await s.commit()
    # Expunge so the session's identity map is empty for the migration —
    # mirrors production, where the migration runs on a session that
    # didn't load this row.
    s.expunge_all()

    inserted = await migrate_legacy_users(s)
    await s.commit()

    legacy = {
        r.oauth_subject
        for r in (await s.execute(select(UserRow))).scalars().all()
        if r.oauth_provider == "legacy"
    }
    # All four legacy ids should be present: user-aaa (pre-existing) +
    # user-bbb / user-ccc / user-ddd (newly migrated).
    assert legacy == {"user-aaa", "user-bbb", "user-ccc", "user-ddd"}
    # user-aaa was a duplicate, so insert count is 3.
    assert inserted == 3


@pytest.mark.asyncio
async def test_run_aborts_when_required_step_fails(session_in_temp_data, monkeypatch):
    s = session_in_temp_data

    async def _boom(session):
        raise RuntimeError("boom")

    monkeypatch.setattr("db.migrations_runtime.migrate_legacy_users", _boom)

    with pytest.raises(RuntimeMigrationError):
        await run_migration(s)

    status = await s.get(MigrationStatus, "json_to_db_v1")
    assert status is None
