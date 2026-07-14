import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import config.settings as app_settings  # noqa: E402


def test_missing_google_oauth_does_not_enable_no_auth_by_default(monkeypatch):
    monkeypatch.setattr(app_settings, "IBM_AUTH_ENABLED", False, raising=True)
    monkeypatch.setattr(app_settings, "OPENRAG_ALLOW_NO_AUTH", False, raising=True)
    monkeypatch.setattr(app_settings, "GOOGLE_OAUTH_CLIENT_ID", "", raising=True)
    monkeypatch.setattr(app_settings, "GOOGLE_OAUTH_CLIENT_SECRET", "", raising=True)

    assert app_settings.is_no_auth_mode() is False


def test_explicit_no_auth_flag_keeps_local_dev_mode_available(monkeypatch):
    monkeypatch.setattr(app_settings, "IBM_AUTH_ENABLED", False, raising=True)
    monkeypatch.setattr(app_settings, "OPENRAG_ALLOW_NO_AUTH", True, raising=True)
    monkeypatch.setattr(app_settings, "GOOGLE_OAUTH_CLIENT_ID", "", raising=True)
    monkeypatch.setattr(app_settings, "GOOGLE_OAUTH_CLIENT_SECRET", "", raising=True)

    assert app_settings.is_no_auth_mode() is True
