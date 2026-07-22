"""Tests for the workspace OAuth connector credential overrides feature flag."""

import pytest

from config.settings import is_workspace_oauth_overrides_enabled


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OPENRAG_WORKSPACE_OAUTH_OVERRIDES_ENABLED", raising=False)
    assert is_workspace_oauth_overrides_enabled() is False


@pytest.mark.parametrize("flag", ["true", "1", "yes", "on", "TRUE"])
def test_enabled_with_truthy_values(monkeypatch, flag):
    monkeypatch.setenv("OPENRAG_WORKSPACE_OAUTH_OVERRIDES_ENABLED", flag)
    assert is_workspace_oauth_overrides_enabled() is True


@pytest.mark.parametrize("flag", ["false", "0", "no", "off", ""])
def test_disabled_with_falsy_values(monkeypatch, flag):
    monkeypatch.setenv("OPENRAG_WORKSPACE_OAUTH_OVERRIDES_ENABLED", flag)
    assert is_workspace_oauth_overrides_enabled() is False
