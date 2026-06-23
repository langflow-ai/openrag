"""Unit tests for startup replica reconciliation.

Covers ``ensure_openrag_index_replicas`` (and the underlying
``_ensure_index_replicas`` helper) in ``utils.opensearch_init``: it should align
each existing OpenRAG index's ``number_of_replicas`` with the configured
``OPENSEARCH_NUMBER_OF_REPLICAS`` and skip indices that do not exist.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

import utils.opensearch_init as osi
from utils.opensearch_init import ensure_openrag_index_replicas

EXPECTED_INDEX_NAMES = [
    "documents",
    "knowledge_filters",
    "api_keys",
    "openrag_dls_principals",
]


def _make_os_client(*, exists: bool, current_replicas: int) -> Any:
    """Build a fake async OpenSearch client with the indices methods used."""
    client = AsyncMock()
    client.indices.exists = AsyncMock(return_value=exists)
    client.indices.get_settings = AsyncMock(
        side_effect=lambda index: {
            index: {"settings": {"index": {"number_of_replicas": str(current_replicas)}}}
        }
    )
    client.indices.put_settings = AsyncMock()
    return client


@pytest.fixture(autouse=True)
def _stable_index_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pin the configured target and the dynamic documents index name, and make
    # sure the IBM dev-mode short-circuit in _ensure_index_replicas stays off.
    monkeypatch.setattr(osi, "OPENSEARCH_NUMBER_OF_REPLICAS", 2)
    monkeypatch.setattr(osi, "get_index_name", lambda: "documents")
    monkeypatch.setattr(osi, "IBM_AUTH_ENABLED", False)
    monkeypatch.setattr(osi, "PLATFORM_AUTH_DEV_MODE", False)
    monkeypatch.setattr(osi, "API_KEYS_INDEX_NAME", "api_keys")
    monkeypatch.setattr(osi, "DLS_PRINCIPAL_INDEX_NAME", "openrag_dls_principals")


@pytest.mark.asyncio
async def test_corrects_replicas_for_all_known_indices() -> None:
    client = _make_os_client(exists=True, current_replicas=0)

    await ensure_openrag_index_replicas(client)

    assert client.indices.put_settings.await_count == len(EXPECTED_INDEX_NAMES)
    corrected = {call.kwargs["index"] for call in client.indices.put_settings.await_args_list}
    assert corrected == set(EXPECTED_INDEX_NAMES)
    for call in client.indices.put_settings.await_args_list:
        assert call.kwargs["body"] == {"index": {"number_of_replicas": 2}}


@pytest.mark.asyncio
async def test_noop_when_replicas_already_match() -> None:
    client = _make_os_client(exists=True, current_replicas=2)

    await ensure_openrag_index_replicas(client)

    client.indices.put_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_skips_missing_indices() -> None:
    client = _make_os_client(exists=False, current_replicas=0)

    await ensure_openrag_index_replicas(client)

    client.indices.get_settings.assert_not_awaited()
    client.indices.put_settings.assert_not_awaited()
