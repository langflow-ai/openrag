"""Regression: persisted connector connections must reload at startup for
dev bucket connectors even in no-auth mode.

Bug: `initialize_services()` skipped `connector_service.initialize()` (which
calls `load_connections()`) whenever no-auth mode was active, on the assumption
that connectors require OAuth. But the Azure Blob bucket connector works in
no-auth dev mode via OPENRAG_DEV_AZURE_BLOB=true. Skipping the load left the
in-memory connections dict empty after a restart, so a saved connection
silently reverted to the "Connect" state until re-saved.

`_should_load_persisted_connections()` encodes the fixed decision; these tests
pin its truth table.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app import container  # noqa: E402


@pytest.mark.parametrize(
    ("no_auth", "dev_azure", "expected"),
    [
        # Authed deployments always load (today's behaviour, unchanged).
        (False, False, True),
        (False, True, True),
        # No-auth without any dev bucket connector: still skipped.
        (True, False, False),
        # The regression: no-auth + dev Azure Blob must load so the saved
        # connection survives a restart.
        (True, True, True),
    ],
)
def test_should_load_persisted_connections(monkeypatch, no_auth, dev_azure, expected):
    monkeypatch.setattr(container, "is_no_auth_mode", lambda: no_auth)
    monkeypatch.setattr(container, "is_dev_azure_blob_enabled", lambda: dev_azure)
    assert container._should_load_persisted_connections() is expected
