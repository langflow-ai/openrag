"""The opensearch_init.wait_for_opensearch wrapper forwards max_retries to the
underlying readiness util.

  * No max_retries arg -> wrapper default of 30 (used by startup_orchestrator /
    init_index).
  * Explicit max_retries -> forwarded verbatim (lifespan passes the configured 100).
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils import opensearch_init  # noqa: E402


@pytest.mark.asyncio
async def test_wrapper_defaults_to_30(monkeypatch):
    inner = AsyncMock()
    monkeypatch.setattr(opensearch_init, "TelemetryClient", MagicMock(send_event=AsyncMock()))
    monkeypatch.setattr("utils.opensearch_utils.wait_for_opensearch", inner)

    fake_client = MagicMock()
    await opensearch_init.wait_for_opensearch(fake_client)

    inner.assert_awaited_once()
    assert inner.await_args.kwargs["max_retries"] == 30


@pytest.mark.asyncio
async def test_wrapper_forwards_explicit_value(monkeypatch):
    inner = AsyncMock()
    monkeypatch.setattr(opensearch_init, "TelemetryClient", MagicMock(send_event=AsyncMock()))
    monkeypatch.setattr("utils.opensearch_utils.wait_for_opensearch", inner)

    fake_client = MagicMock()
    await opensearch_init.wait_for_opensearch(fake_client, max_retries=100)

    inner.assert_awaited_once()
    assert inner.await_args.kwargs["max_retries"] == 100
