"""Tests for the ingest-preview feature flag gating."""

import pytest

from utils.ingest_preview_flag import is_ingest_preview_enabled


@pytest.mark.parametrize("run_mode", ["oss", "saas", "on_prem", ""])
def test_disabled_by_default(monkeypatch, run_mode):
    """Without the opt-in flag, preview is off in every run mode."""
    monkeypatch.setenv("BOMARAG_RUN_MODE", run_mode)
    monkeypatch.delenv("BOMARAG_INGEST_PREVIEW_ENABLED", raising=False)
    assert is_ingest_preview_enabled() is False


@pytest.mark.parametrize("flag", ["true", "1", "yes", "on", "TRUE"])
def test_enabled_when_flag_and_oss(monkeypatch, flag):
    monkeypatch.setenv("BOMARAG_RUN_MODE", "oss")
    monkeypatch.setenv("BOMARAG_INGEST_PREVIEW_ENABLED", flag)
    assert is_ingest_preview_enabled() is True


def test_flag_does_not_enable_saas(monkeypatch):
    """SaaS is temporarily off the allowlist pending product approval."""
    monkeypatch.setenv("BOMARAG_RUN_MODE", "saas")
    monkeypatch.setenv("BOMARAG_INGEST_PREVIEW_ENABLED", "true")
    assert is_ingest_preview_enabled() is False


def test_flag_does_not_enable_on_prem(monkeypatch):
    """The flag is AND-ed with the run mode: on_prem is never eligible."""
    monkeypatch.setenv("BOMARAG_RUN_MODE", "on_prem")
    monkeypatch.setenv("BOMARAG_INGEST_PREVIEW_ENABLED", "true")
    assert is_ingest_preview_enabled() is False
