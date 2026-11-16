"""Tests for the opt-in easyocr confidence threshold setting."""

import pytest

from config.settings import get_easyocr_confidence_threshold

ENV_VAR = "DOCLING_EASYOCR_CONFIDENCE_THRESHOLD"


def test_unset_means_engine_default(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)

    assert get_easyocr_confidence_threshold() is None


def test_blank_means_engine_default(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "  ")

    assert get_easyocr_confidence_threshold() is None


def test_reads_configured_threshold(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "0.3")

    assert get_easyocr_confidence_threshold() == 0.3


@pytest.mark.parametrize("value", ["abc", "0", "-0.2", "1.5", "nan"])
def test_invalid_threshold_falls_back_to_engine_default(monkeypatch, value):
    """A typo must not reach docling-serve, where it would fail every OCR task."""
    monkeypatch.setenv(ENV_VAR, value)

    assert get_easyocr_confidence_threshold() is None
