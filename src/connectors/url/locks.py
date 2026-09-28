"""Cross-process coordination for one managed website source."""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.engine import make_url

from db.engine import get_database_url

_in_process_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _sqlite_lock_path(source_id: str) -> Path | None:
    url = make_url(get_database_url())
    if url.get_backend_name() != "sqlite":
        return None
    database = url.database
    directory = (
        Path(database).parent
        if database and database != ":memory:"
        else Path(tempfile.gettempdir())
    )
    digest = hashlib.sha256(source_id.encode()).hexdigest()
    return directory / f".openrag-url-source-{digest}.lock"


def _acquire_file_lock(path: Path) -> int:
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    return descriptor


def _release_file_lock(descriptor: int) -> None:
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


@asynccontextmanager
async def source_operation_lock(source_id: str):
    """Serialize source writes across processes sharing a SQLite database."""
    async with _in_process_locks[source_id]:
        descriptor: int | None = None
        path = _sqlite_lock_path(source_id)
        if path is not None:
            descriptor = await asyncio.to_thread(_acquire_file_lock, path)
        try:
            yield
        finally:
            if descriptor is not None:
                await asyncio.to_thread(_release_file_lock, descriptor)
