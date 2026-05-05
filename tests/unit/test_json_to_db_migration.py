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

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.migrations_runtime import run as run_migration  # noqa: E402
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
