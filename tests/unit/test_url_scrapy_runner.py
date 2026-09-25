"""Smoke coverage for the isolated Scrapy runner contract."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_scrapy_runner_writes_a_manifest_when_policy_rejects_the_seed(tmp_path):
    """The parent adapter always receives a result, even for blocked URLs.

    ``localhost`` is deliberately rejected by the public-network policy, so
    this exercises the real Scrapy lifecycle without making an external request.
    """
    source_root = Path(__file__).resolve().parents[2] / "src"
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            value for value in (str(source_root), os.environ.get("PYTHONPATH")) if value
        ),
    }
    result = subprocess.run(
        [sys.executable, "-m", "connectors.url.scrapy_runner", "--output-dir", str(tmp_path)],
        input=json.dumps({"seed_url": "http://localhost/"}),
        text=True,
        capture_output=True,
        env=environment,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads((tmp_path / "result.json").read_text())
    assert manifest["complete"] is True
    assert manifest["capped"] is False
    assert manifest["pages"], manifest
    assert manifest["pages"][0]["error"]
