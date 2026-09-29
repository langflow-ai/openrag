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


# ---------------------------------------------------------------------------
# Known failures (see known_failures.txt)
#
# CI runs the full unit suite. Tests that already fail on main are listed in
# known_failures.txt and marked strict xfail here, so a NEW failure turns CI
# red while the existing ones don't — and a listed test that starts passing
# also turns CI red, forcing its line to be deleted. The list can only shrink.
# ---------------------------------------------------------------------------

_KNOWN_FAILURES_FILE = _os.path.join(_os.path.dirname(__file__), "known_failures.txt")


def _read_known_failures() -> tuple[set[str], list[str]]:
    node_ids: set[str] = set()
    ignored: list[str] = []
    try:
        with open(_KNOWN_FAILURES_FILE) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("ignore:"):
                    ignored.append(line[len("ignore:") :].strip())
                else:
                    node_ids.add(line)
    except FileNotFoundError:
        pass
    return node_ids, ignored


_KNOWN_FAILING_NODE_IDS, _KNOWN_UNIMPORTABLE = _read_known_failures()

# Modules that fail at import cannot be xfailed; skip collecting them.
collect_ignore = list(_KNOWN_UNIMPORTABLE)


def pytest_collection_modifyitems(config, items):
    collected = set()
    for item in items:
        node_id = item.nodeid
        if node_id in _KNOWN_FAILING_NODE_IDS:
            collected.add(node_id)
            item.add_marker(
                pytest.mark.xfail(
                    strict=True,
                    reason="Known failure on main (tests/unit/known_failures.txt). "
                    "If this now passes, delete its line from that file.",
                )
            )

    # In CI the whole suite is collected, so every listed id must exist. A stale
    # or mistyped entry would otherwise silently stop protecting anything.
    if _os.environ.get("OPENRAG_ENFORCE_KNOWN_FAILURES") == "1":
        stale = sorted(_KNOWN_FAILING_NODE_IDS - collected)
        if stale:
            raise pytest.UsageError(
                "tests/unit/known_failures.txt lists tests that were not collected "
                "(renamed, deleted, or mistyped). Remove or fix these lines:\n  "
                + "\n  ".join(stale)
            )


@pytest.fixture(autouse=True)
def _reset_filename_claims():
    """Per-test, drop in-flight filename claims.

    In production TaskService releases a file's claim when it reaches a
    terminal state, but tests drive `processor.process_item` directly and never
    pass through that release — a leaked claim would make a later test's ingest
    of the same filename resolve as a duplicate.
    """
    try:
        from utils.filename_claims import filename_claims
    except ImportError:
        yield
        return

    filename_claims.clear()
    yield
    filename_claims.clear()
