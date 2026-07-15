"""Unit tests for the IBM COS connector's `is_available` gating.

Covers IBM_AUTH_ENABLED / OPENRAG_DEV_IBM_COS, mirroring the equivalent
Azure Blob coverage (tests/unit/connectors/test_azure_blob_connector.py).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from enhancements.connectors.ibm_cos import connector as ibm_cos_connector  # noqa: E402
from enhancements.connectors.ibm_cos.connector import IBMCOSConnector  # noqa: E402


def test_is_available_gated_on_ibm_auth_enabled(monkeypatch):
    monkeypatch.setattr(ibm_cos_connector, "IBM_AUTH_ENABLED", True)
    monkeypatch.setattr(ibm_cos_connector, "is_dev_ibm_cos_enabled", lambda: False)
    assert IBMCOSConnector.is_available(MagicMock()) is True
    monkeypatch.setattr(ibm_cos_connector, "IBM_AUTH_ENABLED", False)
    assert IBMCOSConnector.is_available(MagicMock()) is False


def test_is_available_dev_flag_bypasses_ibm_auth(monkeypatch):
    monkeypatch.setattr(ibm_cos_connector, "IBM_AUTH_ENABLED", False)
    monkeypatch.setattr(ibm_cos_connector, "is_dev_ibm_cos_enabled", lambda: True)
    assert IBMCOSConnector.is_available(MagicMock()) is True


def test_is_dev_ibm_cos_enabled_defaults_false_when_unset(monkeypatch):
    """Regression: must default to disabled, or IBM COS becomes available in
    every deployment (including production) whenever OPENRAG_DEV_IBM_COS is
    simply unset, defeating the point of the dev-only bypass."""
    from config.settings import is_dev_ibm_cos_enabled

    monkeypatch.delenv("OPENRAG_DEV_IBM_COS", raising=False)
    assert is_dev_ibm_cos_enabled() is False
