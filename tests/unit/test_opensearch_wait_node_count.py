"""The OpenSearch readiness probe (wait_for_opensearch) gates on data-node,
cluster-manager, and coordinating-node counts behind the OPENSEARCH_NODE_COUNT_CHECK
flag.

Cases:
  * Flag on, all counts met (>= expected):   returns without raising.
  * Flag on, data-node count short:          raises OpenSearchNotReadyError.
  * Flag on, cluster-manager count short:    raises OpenSearchNotReadyError.
  * Flag on, coordinating count short:       raises OpenSearchNotReadyError.
  * Flag off:                                returns regardless of counts.
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


def _fake_os_client(
    data_nodes: int = 2, cluster_managers: int = 2, coordinating: int = 2
) -> MagicMock:
    client = MagicMock()
    client.ping = AsyncMock(return_value=True)
    client.cluster.health = AsyncMock(
        return_value={"status": "green", "number_of_data_nodes": data_nodes}
    )

    async def _perform_request(method, path, *args, **kwargs):
        if "cluster_manager:true" in path:
            return {"_nodes": {"successful": cluster_managers}}
        if "coordinating_only:true" in path:
            return {"_nodes": {"successful": coordinating}}
        raise AssertionError(f"unexpected request path: {path}")

    client.transport.perform_request = AsyncMock(side_effect=_perform_request)
    return client


def _patch_settings(monkeypatch, *, enabled=True, data=2, managers=2, coordinating=2):
    monkeypatch.setattr("config.settings.OPENSEARCH_NODE_COUNT_CHECK_ENABLED", enabled)
    monkeypatch.setattr("config.settings.OPENSEARCH_EXPECTED_DATA_NODE_COUNT", data)
    monkeypatch.setattr("config.settings.OPENSEARCH_EXPECTED_CLUSTER_MANAGER_COUNT", managers)
    monkeypatch.setattr("config.settings.OPENSEARCH_EXPECTED_COORDINATING_NODE_COUNT", coordinating)


@pytest.mark.asyncio
async def test_returns_when_all_counts_met(monkeypatch):
    _patch_settings(monkeypatch)
    client = _fake_os_client(data_nodes=2, cluster_managers=2, coordinating=2)
    # Should not raise.
    await wait_for_opensearch(client, max_retries=1, base_delay=0.0, max_delay=0.0)


@pytest.mark.asyncio
async def test_raises_when_data_nodes_short(monkeypatch):
    _patch_settings(monkeypatch)
    client = _fake_os_client(data_nodes=1, cluster_managers=2, coordinating=2)
    with pytest.raises(OpenSearchNotReadyError):
        await wait_for_opensearch(client, max_retries=2, base_delay=0.0, max_delay=0.0)


@pytest.mark.asyncio
async def test_raises_when_cluster_manager_count_short(monkeypatch):
    _patch_settings(monkeypatch)
    client = _fake_os_client(data_nodes=2, cluster_managers=1, coordinating=2)
    with pytest.raises(OpenSearchNotReadyError):
        await wait_for_opensearch(client, max_retries=2, base_delay=0.0, max_delay=0.0)


@pytest.mark.asyncio
async def test_raises_when_coordinating_count_short(monkeypatch):
    _patch_settings(monkeypatch)
    client = _fake_os_client(data_nodes=2, cluster_managers=2, coordinating=1)
    with pytest.raises(OpenSearchNotReadyError):
        await wait_for_opensearch(client, max_retries=2, base_delay=0.0, max_delay=0.0)


@pytest.mark.asyncio
async def test_returns_when_flag_disabled(monkeypatch):
    _patch_settings(monkeypatch, enabled=False)
    client = _fake_os_client(data_nodes=1, cluster_managers=1, coordinating=1)
    # Flag off -> counts ignored, returns despite short counts.
    await wait_for_opensearch(client, max_retries=1, base_delay=0.0, max_delay=0.0)
