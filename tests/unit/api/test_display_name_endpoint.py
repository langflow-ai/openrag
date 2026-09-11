"""Unit tests for PATCH /api/users/me/display-name.

Tests both auth modes:
  - No-auth mode  → stores name in workspace meta via merge_section_keys
  - Authenticated → updates the users table row via UserRepo.update_display_name
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from api.users import DisplayNameBody, update_my_display_name  # noqa: E402
from db.repositories import WorkspaceConfigRepo  # noqa: E402
from session_manager import User  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _make_user(user_id: str = "u1", provider: str = "google") -> User:
    u = MagicMock(spec=User)
    u.user_id = user_id
    u.provider = provider
    return u


# ---------------------------------------------------------------------------
# No-auth mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_auth_sets_display_name(session_factory):
    """Sets no_auth_display_name in meta when name is provided."""
    async with session_factory() as session:
        with patch("config.settings.is_no_auth_mode", return_value=True):
            body = DisplayNameBody(display_name="Alice")
            user = _make_user()
            response = await update_my_display_name(body=body, user=user, session=session)

    assert response.display_name == "Alice"

    # Confirm the value was persisted in the DB
    async with session_factory() as s:
        meta = await WorkspaceConfigRepo(s).get_section("meta") or {}
    assert meta.get("no_auth_display_name") == "Alice"


@pytest.mark.asyncio
async def test_no_auth_clears_display_name(session_factory):
    """Passing null removes the key from meta."""
    # Pre-seed the name
    async with session_factory() as s:
        await WorkspaceConfigRepo(s).merge_section_keys(
            "meta", updates={"no_auth_display_name": "Bob"}
        )
        await s.commit()

    async with session_factory() as session:
        with patch("config.settings.is_no_auth_mode", return_value=True):
            body = DisplayNameBody(display_name=None)
            response = await update_my_display_name(body=body, user=_make_user(), session=session)

    assert response.display_name is None
    async with session_factory() as s:
        meta = await WorkspaceConfigRepo(s).get_section("meta") or {}
    assert "no_auth_display_name" not in meta


@pytest.mark.asyncio
async def test_no_auth_strips_and_truncates_name(session_factory):
    """Leading/trailing whitespace is stripped; names over 80 chars are capped."""
    long_name = "A" * 100
    async with session_factory() as session:
        with patch("config.settings.is_no_auth_mode", return_value=True):
            body = DisplayNameBody(display_name=f"  {long_name}  ")
            response = await update_my_display_name(body=body, user=_make_user(), session=session)

    assert len(response.display_name) == 80


@pytest.mark.asyncio
async def test_no_auth_empty_string_treated_as_null(session_factory):
    """An empty/whitespace-only display_name clears the field (same as null)."""
    async with session_factory() as s:
        await WorkspaceConfigRepo(s).merge_section_keys(
            "meta", updates={"no_auth_display_name": "Existing"}
        )
        await s.commit()

    async with session_factory() as session:
        with patch("config.settings.is_no_auth_mode", return_value=True):
            body = DisplayNameBody(display_name="   ")
            response = await update_my_display_name(body=body, user=_make_user(), session=session)

    assert response.display_name is None

    async with session_factory() as s:
        meta = await WorkspaceConfigRepo(s).get_section("meta") or {}
    assert "no_auth_display_name" not in meta


# ---------------------------------------------------------------------------
# Authenticated mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticated_sets_display_name():
    """Calls UserRepo.update_display_name with the sanitized name."""
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_db_user = MagicMock()
    mock_db_user.id = "db-u1"

    mock_user_repo = AsyncMock()
    mock_user_repo.get_by_oauth = AsyncMock(return_value=mock_db_user)
    mock_user_repo.update_display_name = AsyncMock()

    with (
        patch("config.settings.is_no_auth_mode", return_value=False),
        patch("api.users.UserRepo", return_value=mock_user_repo),
    ):
        body = DisplayNameBody(display_name="  Charlie  ")
        response = await update_my_display_name(body=body, user=_make_user(), session=mock_session)

    assert response.display_name == "Charlie"
    mock_user_repo.update_display_name.assert_awaited_once_with("db-u1", "Charlie")
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_authenticated_clears_display_name():
    """Passing null calls update_display_name with None."""
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_db_user = MagicMock()
    mock_db_user.id = "db-u1"

    mock_user_repo = AsyncMock()
    mock_user_repo.get_by_oauth = AsyncMock(return_value=mock_db_user)
    mock_user_repo.update_display_name = AsyncMock()

    with (
        patch("config.settings.is_no_auth_mode", return_value=False),
        patch("api.users.UserRepo", return_value=mock_user_repo),
    ):
        body = DisplayNameBody(display_name=None)
        response = await update_my_display_name(body=body, user=_make_user(), session=mock_session)

    assert response.display_name is None
    mock_user_repo.update_display_name.assert_awaited_once_with("db-u1", None)


@pytest.mark.asyncio
async def test_authenticated_404_when_user_not_found():
    """Returns 404 if the user row doesn't exist in either lookup."""
    mock_session = AsyncMock()

    mock_user_repo = AsyncMock()
    mock_user_repo.get_by_oauth = AsyncMock(return_value=None)
    mock_user_repo.get_by_id = AsyncMock(return_value=None)

    with (
        patch("config.settings.is_no_auth_mode", return_value=False),
        patch("api.users.UserRepo", return_value=mock_user_repo),
    ):
        body = DisplayNameBody(display_name="Ghost")
        with pytest.raises(HTTPException) as exc_info:
            await update_my_display_name(body=body, user=_make_user(), session=mock_session)

    assert exc_info.value.status_code == 404
