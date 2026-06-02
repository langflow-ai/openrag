"""SessionOwnershipService — hybrid / db / files mode coverage."""

import json
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.repositories import SessionOwnershipRepo  # noqa: E402
from services.session_ownership_service import (  # noqa: E402
    SessionOwnershipService,
)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Redirect the service's JSON file into a tmp dir."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    json_path = data_dir / "session_ownership.json"
    # The service resolves the path via get_data_file at construction —
    # patch it to return our tmp path.
    monkeypatch.setattr(
        "services.session_ownership_service.get_data_file",
        lambda name: str(data_dir / name),
    )
    yield json_path


def _svc(session_factory) -> SessionOwnershipService:
    return SessionOwnershipService(session_factory=session_factory)


@pytest.mark.asyncio
async def test_db_mode_writes_to_db_only(monkeypatch, tmp_data_dir, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    svc = _svc(session_factory)

    await svc.claim_session("user-a", "sess-1")

    # JSON never created
    assert not tmp_data_dir.exists()

    # DB has the row
    async with session_factory() as session:
        row = await SessionOwnershipRepo(session).get("sess-1")
        assert row is not None
        assert row.user_id == "user-a"


@pytest.mark.asyncio
async def test_files_mode_writes_to_json_only(monkeypatch, tmp_data_dir, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(session_factory)

    await svc.claim_session("user-a", "sess-1")

    # JSON file created
    assert tmp_data_dir.exists()
    payload = json.loads(tmp_data_dir.read_text())
    assert payload["sess-1"]["user_id"] == "user-a"

    # DB untouched
    async with session_factory() as session:
        row = await SessionOwnershipRepo(session).get("sess-1")
        assert row is None


@pytest.mark.asyncio
async def test_hybrid_mode_writes_both(monkeypatch, tmp_data_dir, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = _svc(session_factory)

    await svc.claim_session("user-a", "sess-1")

    assert tmp_data_dir.exists()
    async with session_factory() as session:
        row = await SessionOwnershipRepo(session).get("sess-1")
        assert row is not None


@pytest.mark.asyncio
async def test_db_mode_ignores_pre_existing_json(monkeypatch, tmp_data_dir, session_factory):
    """Stale JSON on disk must not bleed through in db mode."""
    tmp_data_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp_data_dir.write_text(json.dumps({
        "ghost-sess": {"user_id": "ghost-user", "created_at": "x", "last_accessed": "x"}
    }))

    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    svc = _svc(session_factory)

    owner = await svc.get_session_owner("ghost-sess")
    assert owner is None  # JSON ignored


@pytest.mark.asyncio
async def test_cross_user_ownership_check(monkeypatch, tmp_data_dir, session_factory):
    """User B must not see User A's sessions in any mode."""
    for mode in ("db", "files", "hybrid"):
        monkeypatch.setenv("OPENRAG_STORAGE_MODE", mode)
        # Fresh service per mode so the in-memory dict and JSON are reset
        if tmp_data_dir.exists():
            tmp_data_dir.unlink()
        svc = _svc(session_factory)

        await svc.claim_session("alice", f"sess-{mode}")
        assert await svc.is_session_owned_by_user(f"sess-{mode}", "alice") is True
        assert await svc.is_session_owned_by_user(f"sess-{mode}", "bob") is False


@pytest.mark.asyncio
async def test_release_only_owner_can_release(monkeypatch, tmp_data_dir, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    svc = _svc(session_factory)

    await svc.claim_session("alice", "sess-1")
    # Mallory tries to steal
    released = await svc.release_session("mallory", "sess-1")
    assert released is False

    # Alice can release
    released = await svc.release_session("alice", "sess-1")
    assert released is True
    assert await svc.get_session_owner("sess-1") is None
