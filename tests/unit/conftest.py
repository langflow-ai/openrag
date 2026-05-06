"""Unit test configuration.

Overrides the session-scoped onboard_system fixture from the root conftest
so that unit tests don't require running infrastructure (Langflow, OpenSearch, etc.).

Also forces every unit test to use an in-memory SQLite for the RBAC layer
so test fixtures cannot accidentally pollute the dev `data/openrag.db` file.
"""

# CRITICAL: set DATABASE_URL BEFORE any module imports `db.engine`. This
# guarantees that even if a test imports something that triggers
# `init_engine()` at import time, the engine binds to an in-memory DB.
import os as _os
_os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# Defensive default: pin OPENRAG_RBAC_ENFORCE=true for unit tests so a
# developer who has the kill switch in their local `.env` doesn't
# silently make every 403-asserting test pass-through. Tests that
# explicitly want the bypass override this via monkeypatch.
_os.environ["OPENRAG_RBAC_ENFORCE"] = "true"

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(scope="session", autouse=True)
async def onboard_system():
    """No-op override — unit tests mock their own dependencies."""
    yield


@pytest.fixture(autouse=True)
def _reset_db_engine_module_state(monkeypatch):
    """Defensive: per-test, ensure `db.engine`'s module-level singletons
    don't leak across tests. Most tests build their own AsyncEngine via
    `create_async_engine(...)` and never touch the module-level engine,
    but if a code path *does* reach for it, this fixture forces a clean
    re-init bound to the in-memory URL set above.
    """
    try:
        import db.engine as _engine_mod
        monkeypatch.setattr(_engine_mod, "_engine", None, raising=False)
        monkeypatch.setattr(_engine_mod, "SessionLocal", None, raising=False)
    except ImportError:
        pass
    yield
