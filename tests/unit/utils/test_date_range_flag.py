"""Tests for the date range v2 feature flag gating."""

import pytest

from utils.date_range_flag import is_date_range_v2_enabled


@pytest.mark.parametrize("run_mode", ["oss", "saas", "on_prem", ""])
def test_disabled_by_default(monkeypatch, run_mode):
    monkeypatch.setenv("OPENRAG_RUN_MODE", run_mode)
    monkeypatch.delenv("OPENRAG_DATE_RANGE_V2_ENABLED", raising=False)
    assert is_date_range_v2_enabled() is False


@pytest.mark.parametrize("flag", ["true", "1", "yes", "on", "TRUE", " On "])
def test_enabled_when_flag_and_oss(monkeypatch, flag):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setenv("OPENRAG_DATE_RANGE_V2_ENABLED", flag)
    assert is_date_range_v2_enabled() is True


@pytest.mark.parametrize("run_mode", ["saas", "on_prem"])
def test_flag_does_not_enable_other_run_modes(monkeypatch, run_mode):
    monkeypatch.setenv("OPENRAG_RUN_MODE", run_mode)
    monkeypatch.setenv("OPENRAG_DATE_RANGE_V2_ENABLED", "true")
    assert is_date_range_v2_enabled() is False


@pytest.mark.parametrize("flag", ["maybe", "2", "enabled", "false", "0", ""])
def test_garbage_values_are_off(monkeypatch, flag):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setenv("OPENRAG_DATE_RANGE_V2_ENABLED", flag)
    assert is_date_range_v2_enabled() is False
