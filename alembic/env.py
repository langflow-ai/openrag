"""Alembic env — supports both sync (offline / CLI) and async runtimes.

DATABASE_URL is resolved via db.engine.get_database_url so the same code
path applies whether you run alembic from the CLI or programmatically
during app startup.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# Make `src/` importable
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from db.base import metadata as base_metadata  # noqa: E402
from db.engine import get_database_url  # noqa: E402
import db.models  # noqa: E402,F401  (registers tables on metadata)
from sqlmodel import SQLModel  # noqa: E402

config = context.config

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        pass

target_metadata = SQLModel.metadata


def _sync_url() -> str:
    """Alembic prefers a sync URL for offline mode. Convert async drivers."""
    url = get_database_url()
    return (
        url.replace("+aiosqlite", "")
        .replace("postgresql+asyncpg", "postgresql+psycopg")
        .replace("mysql+aiomysql", "mysql+pymysql")
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite-friendly
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable: AsyncEngine = create_async_engine(
        get_database_url(), poolclass=pool.NullPool, future=True
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
