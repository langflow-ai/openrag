"""The OpenSearch readiness probe (wait_for_opensearch) gates on cluster node
counts behind the OPENSEARCH_NODE_COUNT_CHECK flag.

Cases:
  * Flag on, counts met (>= expected): returns without raising.
  * Flag on, counts short:             raises OpenSearchNotReadyError after retries.
  * Flag off:                          returns regardless of node counts.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.opensearch_utils import (  # noqa: E402
    OpenSearchNotReadyError,
    wait_for_opensearch,
)


def _fake_os_client(health: dict) -> MagicMock:
    client = MagicMock()
    client.ping = AsyncMock(return_value=True)
    client.cluster.health = AsyncMock(return_value=health)
    return client


@pytest.mark.asyncio
async def test_returns_when_node_counts_met(monkeypatch):
    monkeypatch.setattr("config.settings.OPENSEARCH_NODE_COUNT_CHECK_ENABLED", True)
    monkeypatch.setattr("config.settings.OPENSEARCH_EXPECTED_NODE_COUNT", 9)
    monkeypatch.setattr("config.settings.OPENSEARCH_EXPECTED_DATA_NODE_COUNT", 3)

    client = _fake_os_client(
        {"status": "green", "number_of_nodes": 9, "number_of_data_nodes": 3}
    )
    # Should not raise.
    await wait_for_opensearch(client, max_retries=1, base_delay=0.0, max_delay=0.0)


@pytest.mark.asyncio
async def test_raises_when_node_counts_short(monkeypatch):
    monkeypatch.setattr("config.settings.OPENSEARCH_NODE_COUNT_CHECK_ENABLED", True)
    monkeypatch.setattr("config.settings.OPENSEARCH_EXPECTED_NODE_COUNT", 9)
    monkeypatch.setattr("config.settings.OPENSEARCH_EXPECTED_DATA_NODE_COUNT", 3)

    client = _fake_os_client(
        {"status": "green", "number_of_nodes": 1, "number_of_data_nodes": 1}
    )
    with pytest.raises(OpenSearchNotReadyError):
        await wait_for_opensearch(client, max_retries=2, base_delay=0.0, max_delay=0.0)


@pytest.mark.asyncio
async def test_returns_when_flag_disabled(monkeypatch):
    monkeypatch.setattr("config.settings.OPENSEARCH_NODE_COUNT_CHECK_ENABLED", False)
    monkeypatch.setattr("config.settings.OPENSEARCH_EXPECTED_NODE_COUNT", 9)
    monkeypatch.setattr("config.settings.OPENSEARCH_EXPECTED_DATA_NODE_COUNT", 3)

    client = _fake_os_client(
        {"status": "green", "number_of_nodes": 1, "number_of_data_nodes": 1}
    )
    # Flag off -> node counts ignored, returns despite short counts.
    await wait_for_opensearch(client, max_retries=1, base_delay=0.0, max_delay=0.0)
