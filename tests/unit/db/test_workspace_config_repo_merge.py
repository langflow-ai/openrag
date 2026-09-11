"""Unit tests for WorkspaceConfigRepo.merge_section_keys.

Covers the atomic read-merge-write introduced to fix the
no_auth_display_name / edited concurrent-update race.
"""

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

import db.models  # noqa: E402,F401  — populates SQLModel metadata
from db.repositories.workspace_config_repo import WorkspaceConfigRepo  # noqa: E402


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


# ---------------------------------------------------------------------------
# merge_section_keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_creates_row_when_section_missing(session_factory):
    """First call inserts the row with only the supplied keys."""
    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        row = await repo.merge_section_keys("meta", updates={"no_auth_display_name": "Alice"})
        await s.commit()

    assert row.value == {"no_auth_display_name": "Alice"}


@pytest.mark.asyncio
async def test_merge_adds_key_without_overwriting_others(session_factory):
    """A second caller writing a different key must not clobber the first."""
    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        await repo.merge_section_keys("meta", updates={"no_auth_display_name": "Alice"})
        await s.commit()

    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        row = await repo.merge_section_keys("meta", updates={"edited": True})
        await s.commit()

    assert row.value == {"no_auth_display_name": "Alice", "edited": True}


@pytest.mark.asyncio
async def test_merge_deletion_removes_key_preserves_others(session_factory):
    """Passing a key in *deletions* removes it while leaving other keys intact."""
    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        await repo.merge_section_keys(
            "meta",
            updates={"no_auth_display_name": "Alice", "edited": True},
        )
        await s.commit()

    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        row = await repo.merge_section_keys(
            "meta",
            updates={},
            deletions={"no_auth_display_name"},
        )
        await s.commit()

    assert "no_auth_display_name" not in row.value
    assert row.value.get("edited") is True


@pytest.mark.asyncio
async def test_merge_deletion_of_absent_key_is_noop(session_factory):
    """Deleting a key that was never set must not raise or corrupt the row."""
    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        await repo.merge_section_keys("meta", updates={"edited": False})
        await s.commit()

    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        row = await repo.merge_section_keys(
            "meta",
            updates={},
            deletions={"no_auth_display_name"},
        )
        await s.commit()

    assert row.value == {"edited": False}


@pytest.mark.asyncio
async def test_merge_update_overwrites_existing_key(session_factory):
    """Passing the same key in *updates* replaces its previous value."""
    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        await repo.merge_section_keys("meta", updates={"no_auth_display_name": "Old"})
        await s.commit()

    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        row = await repo.merge_section_keys("meta", updates={"no_auth_display_name": "New"})
        await s.commit()

    assert row.value["no_auth_display_name"] == "New"


@pytest.mark.asyncio
async def test_merge_empty_updates_and_no_deletions_is_noop(session_factory):
    """Calling with no updates and no deletions preserves the row unchanged."""
    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        await repo.merge_section_keys("meta", updates={"k": "v"})
        await s.commit()

    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        row = await repo.merge_section_keys("meta", updates={})
        await s.commit()

    assert row.value == {"k": "v"}


# ---------------------------------------------------------------------------
# Existing upsert still works (regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_still_replaces_section_wholesale(session_factory):
    """upsert() must still overwrite the whole section dict."""
    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        await repo.upsert("knowledge", {"a": 1, "b": 2})
        await s.commit()

    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        row = await repo.upsert("knowledge", {"a": 99})
        await s.commit()

    assert row.value == {"a": 99}
    assert "b" not in row.value


# ---------------------------------------------------------------------------
# Concurrent-style coverage: two sequential merges into the same section
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sequential_merges_into_absent_section_preserve_all_keys(session_factory):
    """Two callers writing different keys into a previously absent section.

    Within the single-worker asyncio model (AGENTS.md) these interleave only
    at await points; the SELECT FOR UPDATE + flush sequence is atomic per
    caller.  Both keys must survive.
    """
    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        # First caller inserts the row
        await repo.merge_section_keys("meta", updates={"key_a": "alpha"})
        # Second caller (same session, as would happen in practice under
        # asyncio cooperative scheduling) merges a different key
        await repo.merge_section_keys("meta", updates={"key_b": "beta"})
        await s.commit()

    async with session_factory() as s:
        value = await WorkspaceConfigRepo(s).get_section("meta")

    assert value == {"key_a": "alpha", "key_b": "beta"}


@pytest.mark.asyncio
async def test_sequential_merges_into_existing_section_preserve_all_keys(session_factory):
    """Two callers writing different keys into an already-existing section."""
    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        await repo.merge_section_keys("meta", updates={"existing": True})
        await s.commit()

    async with session_factory() as s:
        repo = WorkspaceConfigRepo(s)
        await repo.merge_section_keys("meta", updates={"caller_a": 1})
        await repo.merge_section_keys("meta", updates={"caller_b": 2})
        await s.commit()

    async with session_factory() as s:
        value = await WorkspaceConfigRepo(s).get_section("meta")

    assert value == {"existing": True, "caller_a": 1, "caller_b": 2}
