"""
Tests for utils/env_utils.py
Validates safe_int, safe_float, get_env_int, and get_env_float.
All tests are pure unit tests with no external dependencies.
"""

import pytest

from utils.env_utils import get_env_float, get_env_int, safe_float, safe_int


# ── safe_int ──────────────────────────────────────────────────────────────────


class TestSafeInt:
    """safe_int must parse integers and fall back gracefully on bad input."""

    def test_returns_valid_integer(self):
        assert safe_int("42", 0) == 42

    def test_returns_negative_integer(self):
        assert safe_int("-7", 0) == -7

    def test_returns_zero_string(self):
        assert safe_int("0", 99) == 0

    def test_returns_default_for_none(self):
        assert safe_int(None, 5) == 5

    def test_returns_default_for_empty_string(self):
        assert safe_int("", 5) == 5

    def test_returns_default_for_non_numeric_string(self):
        assert safe_int("abc", 10) == 10

    def test_returns_default_for_float_string(self):
        """A bare float string ('3.14') is not a valid int literal."""
        assert safe_int("3.14", 1) == 1

    def test_returns_default_for_whitespace(self):
        """Whitespace-only strings are not valid integers."""
        assert safe_int("   ", 7) == 7

    def test_accepts_int_value_directly(self):
        """Passing an actual int (not a string) should work via int()."""
        assert safe_int(100, 0) == 100

    def test_returns_default_when_none_and_default_is_zero(self):
        assert safe_int(None, 0) == 0


# ── safe_float ────────────────────────────────────────────────────────────────


class TestSafeFloat:
    """safe_float must parse floats and fall back gracefully on bad input."""

    def test_returns_valid_float(self):
        assert safe_float("3.14", 0.0) == pytest.approx(3.14)

    def test_returns_negative_float(self):
        assert safe_float("-2.5", 0.0) == pytest.approx(-2.5)

    def test_returns_integer_string_as_float(self):
        assert safe_float("10", 0.0) == pytest.approx(10.0)

    def test_returns_zero_string(self):
        assert safe_float("0.0", 99.9) == pytest.approx(0.0)

    def test_returns_default_for_none(self):
        assert safe_float(None, 1.5) == pytest.approx(1.5)

    def test_returns_default_for_empty_string(self):
        assert safe_float("", 2.0) == pytest.approx(2.0)

    def test_returns_default_for_non_numeric_string(self):
        assert safe_float("not_a_number", 9.9) == pytest.approx(9.9)

    def test_returns_default_for_whitespace(self):
        assert safe_float("   ", 0.5) == pytest.approx(0.5)

    def test_accepts_float_value_directly(self):
        """Passing an actual float (not a string) should work via float()."""
        assert safe_float(2.718, 0.0) == pytest.approx(2.718)

    def test_returns_default_when_none_and_default_is_zero(self):
        assert safe_float(None, 0.0) == pytest.approx(0.0)


# ── get_env_int ───────────────────────────────────────────────────────────────


class TestGetEnvInt:
    """get_env_int reads an env var and parses it as an integer."""

    def test_returns_env_var_as_int(self, monkeypatch):
        monkeypatch.setenv("TEST_INT_VAR", "25")
        assert get_env_int("TEST_INT_VAR", 0) == 25

    def test_returns_default_when_var_not_set(self, monkeypatch):
        monkeypatch.delenv("TEST_INT_VAR", raising=False)
        assert get_env_int("TEST_INT_VAR", 42) == 42

    def test_returns_default_when_var_is_empty(self, monkeypatch):
        monkeypatch.setenv("TEST_INT_VAR", "")
        assert get_env_int("TEST_INT_VAR", 7) == 7

    def test_returns_default_when_var_is_non_numeric(self, monkeypatch):
        monkeypatch.setenv("TEST_INT_VAR", "oops")
        assert get_env_int("TEST_INT_VAR", 3) == 3

    def test_returns_negative_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_INT_VAR", "-100")
        assert get_env_int("TEST_INT_VAR", 0) == -100

    def test_returns_zero_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_INT_VAR", "0")
        assert get_env_int("TEST_INT_VAR", 99) == 0


# ── get_env_float ─────────────────────────────────────────────────────────────


class TestGetEnvFloat:
    """get_env_float reads an env var and parses it as a float."""

    def test_returns_env_var_as_float(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_VAR", "1.5")
        assert get_env_float("TEST_FLOAT_VAR", 0.0) == pytest.approx(1.5)

    def test_returns_default_when_var_not_set(self, monkeypatch):
        monkeypatch.delenv("TEST_FLOAT_VAR", raising=False)
        assert get_env_float("TEST_FLOAT_VAR", 3.14) == pytest.approx(3.14)

    def test_returns_default_when_var_is_empty(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_VAR", "")
        assert get_env_float("TEST_FLOAT_VAR", 2.0) == pytest.approx(2.0)

    def test_returns_default_when_var_is_non_numeric(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_VAR", "invalid")
        assert get_env_float("TEST_FLOAT_VAR", 0.5) == pytest.approx(0.5)

    def test_returns_integer_string_as_float(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_VAR", "10")
        assert get_env_float("TEST_FLOAT_VAR", 0.0) == pytest.approx(10.0)

    def test_returns_negative_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_VAR", "-0.75")
        assert get_env_float("TEST_FLOAT_VAR", 0.0) == pytest.approx(-0.75)

    def test_returns_zero_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_VAR", "0.0")
        assert get_env_float("TEST_FLOAT_VAR", 99.9) == pytest.approx(0.0)
