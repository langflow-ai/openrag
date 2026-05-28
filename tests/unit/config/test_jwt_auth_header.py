"""config.settings.get_jwt_auth_header — per-call accessor for the header that
carries a gateway-forwarded JWT to the /v1 (API-key) surface."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.settings import get_jwt_auth_header  # noqa: E402


def test_default_header(monkeypatch):
    monkeypatch.delenv("OPENRAG_JWT_AUTH_HEADER", raising=False)
    assert get_jwt_auth_header() == "Authorization"


def test_override_header(monkeypatch):
    monkeypatch.setenv("OPENRAG_JWT_AUTH_HEADER", "X-Forwarded-Access-Token")
    assert get_jwt_auth_header() == "X-Forwarded-Access-Token"
