"""Regression tests for the OPENRAG_SHOW_SHARED_UPLOAD_TOGGLE flag.

This flag lets deployments expose the COS "Make documents available to all
users" toggle independently of OPENRAG_SHOW_PROVIDER_INGEST_SETTINGS, which
gates the rest of the per-upload ingest tuning knobs (chunk size, OCR, etc.).
Make sure to update this test when the flag is removed.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"


def _python_env(env: dict[str, str]) -> dict[str, str]:
    merged = os.environ.copy()
    merged.update(env)
    return merged


def _read_flag(env: dict[str, str]) -> str:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from config import settings; print(settings.OPENRAG_SHOW_SHARED_UPLOAD_TOGGLE)",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=_python_env(env),
        cwd=str(ROOT),
    )
    return result.stdout.splitlines()[-1].strip()


def test_defaults_true_when_unset():
    env = {"PYTHONPATH": str(SRC)}
    env.pop("OPENRAG_SHOW_SHARED_UPLOAD_TOGGLE", None)
    assert _read_flag(env) == "True"


def test_false_when_disabled():
    env = {"OPENRAG_SHOW_SHARED_UPLOAD_TOGGLE": "false", "PYTHONPATH": str(SRC)}
    assert _read_flag(env) == "False"


def test_true_when_enabled():
    env = {"OPENRAG_SHOW_SHARED_UPLOAD_TOGGLE": "true", "PYTHONPATH": str(SRC)}
    assert _read_flag(env) == "True"


def test_independent_of_show_provider_ingest_settings():
    """The shared-only flag can be enabled while the general flag stays off."""
    env = {
        "OPENRAG_SHOW_SHARED_UPLOAD_TOGGLE": "true",
        "OPENRAG_SHOW_PROVIDER_INGEST_SETTINGS": "false",
        "PYTHONPATH": str(SRC),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from config import settings; "
            "print(settings.OPENRAG_SHOW_SHARED_UPLOAD_TOGGLE, "
            "settings.OPENRAG_SHOW_PROVIDER_INGEST_SETTINGS)",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=_python_env(env),
        cwd=str(ROOT),
    )
    assert result.stdout.splitlines()[-1].strip() == "True False"
