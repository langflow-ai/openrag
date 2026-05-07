"""Async SQLAlchemy engine + session factory.

DATABASE_URL is the single switch between SQLite (default) and Postgres.
"""

import os
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.paths import get_data_file
from utils.logging_config import get_logger

logger = get_logger(__name__)

_engine: Optional[AsyncEngine] = None
SessionLocal: Optional[async_sessionmaker[AsyncSession]] = None


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    sqlite_path = os.path.abspath(get_data_file("openrag.db"))
    return f"sqlite+aiosqlite:///{sqlite_path}"


def init_engine() -> AsyncEngine:
    """Initialize the async engine + session factory. Idempotent."""
    global _engine, SessionLocal
    if _engine is not None:
        return _engine

    url = get_database_url()
    is_sqlite = url.startswith("sqlite")

    connect_args = {"check_same_thread": False} if is_sqlite else {}
    _engine = create_async_engine(
        url,
        echo=os.getenv("OPENRAG_DB_ECHO", "false").lower() in ("true", "1", "yes"),
        future=True,
        connect_args=connect_args,
        pool_pre_ping=not is_sqlite,
    )

    SessionLocal = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    dialect = "sqlite" if is_sqlite else "postgres" if "postgres" in url else "other"
    logger.info("DB engine initialized", dialect=dialect)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        return init_engine()
    return _engine


async def dispose_engine() -> None:
    global _engine, SessionLocal
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        SessionLocal = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency body — yields an AsyncSession."""
    if SessionLocal is None:
        init_engine()
    assert SessionLocal is not None
    async with SessionLocal() as session:
        yield session
