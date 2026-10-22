"""Unit tests for FailedIngestionRepo and the registry's blocking rule.

The rule under test: a file is skipped by bucket ingestion only once its retry
budget is spent AND the source version (etag, modified time) is the one that
failed. Changing the file at the source gives it a fresh budget.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401  — populates SQLModel metadata
from db.repositories.failed_ingestion_repo import (  # noqa: E402
    DEFAULT_MAX_ATTEMPTS,
    FailedIngestionRepo,
    max_attempts,
)
from services.failed_ingestion_service import is_blocked  # noqa: E402

USER = "user-1"
CONNECTOR = "aws_s3"
FILE_ID = "bucket::docs/broken.docx"


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


async def _fail(repo, *, etag="e1", modified="2026-01-01T00:00:00Z", error="boom", user=USER):
    return await repo.record_failure(
        user,
        CONNECTOR,
        FILE_ID,
        error,
        filename="broken.docx",
        content_etag=etag,
        modified_time=modified,
    )


# ---------------------------------------------------------------------------
# max_attempts
# ---------------------------------------------------------------------------


def test_max_attempts_defaults_to_three(monkeypatch):
    monkeypatch.delenv("FAILED_INGESTION_MAX_ATTEMPTS", raising=False)
    assert max_attempts() == DEFAULT_MAX_ATTEMPTS == 3


def test_max_attempts_reads_env(monkeypatch):
    monkeypatch.setenv("FAILED_INGESTION_MAX_ATTEMPTS", "5")
    assert max_attempts() == 5


@pytest.mark.parametrize("raw", ["0", "-2", "abc", ""])
def test_max_attempts_ignores_invalid_values(monkeypatch, raw):
    monkeypatch.setenv("FAILED_INGESTION_MAX_ATTEMPTS", raw)
    assert max_attempts() == DEFAULT_MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# record_failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_failure_creates_row_with_one_attempt(session_factory):
    async with session_factory() as s:
        row = await _fail(FailedIngestionRepo(s))
        await s.commit()

    assert row.attempt_count == 1
    assert row.last_error == "boom"
    assert row.filename == "broken.docx"


@pytest.mark.asyncio
async def test_repeat_failure_on_same_version_increments_attempts(session_factory):
    async with session_factory() as s:
        repo = FailedIngestionRepo(s)
        await _fail(repo, error="first")
        row = await _fail(repo, error="second")
        await s.commit()

    assert row.attempt_count == 2
    assert row.last_error == "second"


@pytest.mark.asyncio
async def test_failure_on_changed_etag_restarts_the_budget(session_factory):
    async with session_factory() as s:
        repo = FailedIngestionRepo(s)
        await _fail(repo)
        await _fail(repo)
        row = await _fail(repo, etag="e2")
        await s.commit()

    assert row.attempt_count == 1
    assert row.content_etag == "e2"


@pytest.mark.asyncio
async def test_failure_on_changed_modified_time_restarts_the_budget(session_factory):
    async with session_factory() as s:
        repo = FailedIngestionRepo(s)
        await _fail(repo, etag=None)
        row = await _fail(repo, etag=None, modified="2026-02-01T00:00:00Z")
        await s.commit()

    assert row.attempt_count == 1


@pytest.mark.asyncio
async def test_long_error_is_truncated(session_factory):
    async with session_factory() as s:
        row = await _fail(FailedIngestionRepo(s), error="x" * 10_000)
        await s.commit()

    assert len(row.last_error) == 2000


@pytest.mark.asyncio
async def test_rows_are_scoped_per_user(session_factory):
    async with session_factory() as s:
        repo = FailedIngestionRepo(s)
        await _fail(repo, user="alice")
        await _fail(repo, user="bob")
        await s.commit()

        assert len(await repo.list_for_user("alice")) == 1
        assert len(await repo.list_for_user("bob")) == 1
        assert await repo.list_for_user("carol") == []


# ---------------------------------------------------------------------------
# list / clear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_filters_by_connector_type(session_factory):
    async with session_factory() as s:
        repo = FailedIngestionRepo(s)
        await _fail(repo)
        await repo.record_failure(USER, "ibm_cos", "b::x.pdf", "err")
        await s.commit()

        assert len(await repo.list_for_user(USER)) == 2
        only_s3 = await repo.list_for_user(USER, CONNECTOR)
        assert [r.connector_type for r in only_s3] == [CONNECTOR]


@pytest.mark.asyncio
async def test_clear_removes_one_row(session_factory):
    async with session_factory() as s:
        repo = FailedIngestionRepo(s)
        await _fail(repo)
        await repo.record_failure(USER, CONNECTOR, "bucket::other.pdf", "err")
        await s.commit()

        assert await repo.clear(USER, CONNECTOR, FILE_ID) is True
        assert await repo.clear(USER, CONNECTOR, FILE_ID) is False
        await s.commit()

        remaining = await repo.list_for_user(USER)
        assert [r.file_id for r in remaining] == ["bucket::other.pdf"]


@pytest.mark.asyncio
async def test_clear_does_not_touch_other_users(session_factory):
    async with session_factory() as s:
        repo = FailedIngestionRepo(s)
        await _fail(repo, user="alice")
        await _fail(repo, user="bob")
        await s.commit()

        assert await repo.clear("alice", CONNECTOR, FILE_ID) is True
        await s.commit()

        assert await repo.list_for_user("alice") == []
        assert len(await repo.list_for_user("bob")) == 1


@pytest.mark.asyncio
async def test_clear_all_scopes_to_user_and_optional_connector(session_factory):
    async with session_factory() as s:
        repo = FailedIngestionRepo(s)
        await _fail(repo)
        await repo.record_failure(USER, "ibm_cos", "b::x.pdf", "err")
        await _fail(repo, user="bob")
        await s.commit()

        assert await repo.clear_all(USER, "ibm_cos") == 1
        assert await repo.clear_all(USER) == 1
        await s.commit()

        assert await repo.list_for_user(USER) == []
        assert len(await repo.list_for_user("bob")) == 1


# ---------------------------------------------------------------------------
# is_blocked
# ---------------------------------------------------------------------------


def _row(attempts, etag="e1", modified="2026-01-01T00:00:00Z"):
    return SimpleNamespace(attempt_count=attempts, content_etag=etag, modified_time=modified)


def test_not_blocked_while_budget_remains(monkeypatch):
    monkeypatch.delenv("FAILED_INGESTION_MAX_ATTEMPTS", raising=False)
    assert not is_blocked(_row(2), "e1", "2026-01-01T00:00:00Z")


def test_blocked_once_budget_is_spent_on_same_version(monkeypatch):
    monkeypatch.delenv("FAILED_INGESTION_MAX_ATTEMPTS", raising=False)
    assert is_blocked(_row(3), "e1", "2026-01-01T00:00:00Z")


def test_not_blocked_when_etag_changed(monkeypatch):
    monkeypatch.delenv("FAILED_INGESTION_MAX_ATTEMPTS", raising=False)
    assert not is_blocked(_row(3), "e2", "2026-01-01T00:00:00Z")


def test_not_blocked_when_modified_time_changed(monkeypatch):
    monkeypatch.delenv("FAILED_INGESTION_MAX_ATTEMPTS", raising=False)
    assert not is_blocked(_row(3), "e1", "2026-03-01T00:00:00Z")


def test_blocked_with_no_version_signal_on_either_side(monkeypatch):
    """Failures recorded without etag/modified time still block when the listing has none."""
    monkeypatch.delenv("FAILED_INGESTION_MAX_ATTEMPTS", raising=False)
    assert is_blocked(_row(3, etag=None, modified=None), None, None)


def test_budget_follows_env_override(monkeypatch):
    monkeypatch.setenv("FAILED_INGESTION_MAX_ATTEMPTS", "1")
    assert is_blocked(_row(1), "e1", "2026-01-01T00:00:00Z")
