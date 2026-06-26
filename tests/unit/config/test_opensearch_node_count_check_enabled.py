"""Regression tests for the OpenSearch node-count readiness toggle."""

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


def test_settings_reads_canonical_node_count_env_var():
    env = _python_env(
        {
            "OPENSEARCH_NODE_COUNT_CHECK_ENABLED": "false",
            "PYTHONPATH": str(SRC),
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from config import settings; print(settings.OPENSEARCH_NODE_COUNT_CHECK_ENABLED)",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=str(ROOT),
    )
    assert result.stdout.splitlines()[-1].strip() == "False"
