"""Regression tests for OpenSearch connection pool maxsize configuration."""

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


def test_settings_reads_canonical_pool_maxsize_env_var():
    env = _python_env(
        {
            "OPENSEARCH_POOL_MAXSIZE": "64",
            "PYTHONPATH": str(SRC),
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from config.settings import OPENSEARCH_POOL_MAXSIZE; print(OPENSEARCH_POOL_MAXSIZE)",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=str(ROOT),
    )
    assert result.stdout.splitlines()[-1].strip() == "64"


def test_settings_default_pool_maxsize_fallback():
    env = _python_env(
        {
            "PYTHONPATH": str(SRC),
        }
    )
    env.pop("OPENSEARCH_POOL_MAXSIZE", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from config.settings import OPENSEARCH_POOL_MAXSIZE; print(OPENSEARCH_POOL_MAXSIZE)",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=str(ROOT),
    )
    assert result.stdout.splitlines()[-1].strip() == "8"


def test_opensearch_client_uses_configured_pool_maxsize():
    env = _python_env(
        {
            "OPENSEARCH_POOL_MAXSIZE": "48",
            "PYTHONPATH": str(SRC),
        }
    )
    code = (
        "from config.settings import clients; "
        "client = clients.create_basic_opensearch_client('admin', 'pass'); "
        "client.transport.set_connections([{'host': 'localhost', 'port': 9200}]); "
        "conn = client.transport.get_connection(); "
        "print(conn._limit)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=str(ROOT),
    )
    assert result.stdout.splitlines()[-1].strip() == "48"
