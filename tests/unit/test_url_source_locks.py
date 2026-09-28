"""Cross-process locking coverage for SQLite-backed URL sources."""

import asyncio
import sys

import pytest

from connectors.url.locks import _sqlite_lock_path, source_operation_lock


@pytest.mark.asyncio
async def test_sqlite_source_lock_blocks_another_process(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'openrag.db'}")
    source_id = "source-lock-test"
    lock_path = _sqlite_lock_path(source_id)
    assert lock_path is not None
    ready = tmp_path / "ready"
    acquired = tmp_path / "acquired"
    script = """
import fcntl
import os
import sys
from pathlib import Path

lock_path, ready_path, acquired_path = map(Path, sys.argv[1:])
ready_path.touch()
descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
fcntl.flock(descriptor, fcntl.LOCK_EX)
acquired_path.touch()
fcntl.flock(descriptor, fcntl.LOCK_UN)
os.close(descriptor)
"""

    async with source_operation_lock(source_id):
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            str(lock_path),
            str(ready),
            str(acquired),
        )
        for _ in range(100):
            if ready.exists():
                break
            await asyncio.sleep(0.01)
        assert ready.exists()
        assert not acquired.exists()

    assert await asyncio.wait_for(child.wait(), timeout=1) == 0
    assert acquired.exists()
