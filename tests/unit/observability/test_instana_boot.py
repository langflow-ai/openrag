"""Tests for the Instana enable gate (`observability/instana_boot.py`).

The gate decides whether an APM tracer that monkey-patches httpx, urllib3,
sqlalchemy, starlette and logging gets loaded into the process, so its parsing
is worth pinning: the failure mode is silent (tracing simply never starts).
"""

import sys
from types import SimpleNamespace

import pytest

from observability.instana_boot import INSTANA_ENABLED_ENV_VAR, boot_instana, is_instana_enabled
from utils import logging_config


@pytest.mark.parametrize("value", ["true", "1", "yes"])
def test_accepted_values_enable_tracing(value):
    assert is_instana_enabled(value) is True


@pytest.mark.parametrize("value", ["TRUE", "True", "Yes", "YES"])
def test_accepted_values_are_case_insensitive(value):
    assert is_instana_enabled(value) is True


@pytest.mark.parametrize("value", [" true ", "\ttrue\n"])
def test_surrounding_whitespace_is_ignored(value):
    """A trailing space in a .env line or a Helm value must not disable tracing."""
    assert is_instana_enabled(value) is True


@pytest.mark.parametrize("value", ["false", "0", "no", "", "   ", "on", "enabled", "y"])
def test_everything_else_disables_tracing(value):
    """Only the documented spellings count.

    `on`/`enabled`/`y` are deliberately *not* accepted — this asserts the
    documented set rather than a guess, and keeps the backend in step with the
    operator's isTruthyEnvValue (kubernetes/operator/internal/controller/env.go).
    """
    assert is_instana_enabled(value) is False


def test_unset_variable_disables_tracing(monkeypatch):
    monkeypatch.delenv(INSTANA_ENABLED_ENV_VAR, raising=False)
    assert is_instana_enabled() is False


def test_environment_is_read_when_no_value_is_passed(monkeypatch):
    monkeypatch.setenv(INSTANA_ENABLED_ENV_VAR, "true")
    assert is_instana_enabled() is True


def test_boot_is_a_no_op_when_disabled(monkeypatch):
    """The tracer must not be imported when the flag is off."""
    monkeypatch.setenv(INSTANA_ENABLED_ENV_VAR, "false")
    monkeypatch.delitem(sys.modules, "instana", raising=False)

    assert boot_instana() is False
    assert "instana" not in sys.modules


def test_boot_warns_and_continues_when_the_package_is_missing(monkeypatch):
    """`instana` ships as the optional `apm` extra, so a missing package is not fatal."""
    monkeypatch.setenv(INSTANA_ENABLED_ENV_VAR, "true")
    monkeypatch.delitem(sys.modules, "instana", raising=False)

    class _BlockInstana:
        def find_spec(self, name, path=None, target=None):
            if name == "instana":
                raise ImportError("blocked by test")
            return None

    monkeypatch.setattr(sys, "meta_path", [_BlockInstana(), *sys.meta_path])

    # Assert on the logger call rather than on captured output: structlog is
    # configured against the stderr stream bound at import time, which neither
    # caplog nor capsys/capfd sees from inside a test.
    warnings: list[str] = []
    monkeypatch.setattr(
        logging_config,
        "get_logger",
        lambda *a, **kw: SimpleNamespace(warning=lambda msg, **kw: warnings.append(msg)),
    )

    assert boot_instana() is False
    assert len(warnings) == 1
    assert "uv sync --extra apm" in warnings[0]
