"""OPENRAG_SKIP_OS_SECURITY_SETUP gates the init_index() call to
setup_opensearch_security, but does NOT skip index creation.

Three cases:
  * Flag false (default): security setup IS called.
  * Flag true:            security setup is NOT called.
  * Flag true:            index creation still runs (docs / knowledge_filters /
                          api_keys indices) so SaaS / CPD deployments still
                          get usable indices.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _fake_os_client():
    client = MagicMock()
    # Treat every indices.exists() as False so the create branch runs.
    client.indices.exists = AsyncMock(return_value=False)
    client.indices.create = AsyncMock()
    client.indices.get_settings = AsyncMock(return_value={})
    client.indices.put_settings = AsyncMock()
    client.cluster.put_settings = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_security_setup_called_when_flag_false(monkeypatch):
    import utils.opensearch_init as init_mod

    monkeypatch.setattr(init_mod, "OPENRAG_SKIP_OS_SECURITY_SETUP", False)
    monkeypatch.setattr(init_mod, "IBM_AUTH_ENABLED", False)
    monkeypatch.setattr(init_mod, "PLATFORM_AUTH_DEV_MODE", False)

    os_client = _fake_os_client()
    setup_mock = AsyncMock()

    with (
        patch("utils.opensearch_utils.setup_opensearch_security", setup_mock),
        patch.object(init_mod, "wait_for_opensearch", AsyncMock()),
        patch.object(
            init_mod, "create_index_body", AsyncMock(return_value={"settings": {}, "mappings": {}})
        ),
        patch.object(init_mod, "get_index_name", return_value="documents"),
    ):
        await init_mod.init_index(opensearch_client=os_client, admin_username="alice")

    assert setup_mock.await_count == 1
    args, kwargs = setup_mock.await_args
    assert args[0] is os_client
    assert kwargs.get("admin_username") == "alice"


@pytest.mark.asyncio
async def test_security_setup_skipped_when_flag_true(monkeypatch):
    import utils.opensearch_init as init_mod

    monkeypatch.setattr(init_mod, "OPENRAG_SKIP_OS_SECURITY_SETUP", True)
    monkeypatch.setattr(init_mod, "IBM_AUTH_ENABLED", False)
    monkeypatch.setattr(init_mod, "PLATFORM_AUTH_DEV_MODE", False)

    os_client = _fake_os_client()
    setup_mock = AsyncMock()
    # Spy the bound logger; the project's wrapper doesn't propagate to caplog.
    logger_spy = MagicMock()
    monkeypatch.setattr(init_mod, "logger", logger_spy)

    with (
        patch("utils.opensearch_utils.setup_opensearch_security", setup_mock),
        patch.object(init_mod, "wait_for_opensearch", AsyncMock()),
        patch.object(
            init_mod, "create_index_body", AsyncMock(return_value={"settings": {}, "mappings": {}})
        ),
        patch.object(init_mod, "get_index_name", return_value="documents"),
    ):
        await init_mod.init_index(opensearch_client=os_client, admin_username="bob")

    assert setup_mock.await_count == 0
    info_messages = [call.args[0] for call in logger_spy.info.call_args_list if call.args]
    assert any(
        "Skipping OpenSearch security setup during init_index" in msg for msg in info_messages
    ), f"expected skip log line not emitted; got: {info_messages}"


@pytest.mark.asyncio
async def test_index_creation_still_runs_when_flag_true(monkeypatch):
    """Skipping security setup must NOT skip index creation."""
    import utils.opensearch_init as init_mod

    monkeypatch.setattr(init_mod, "OPENRAG_SKIP_OS_SECURITY_SETUP", True)
    monkeypatch.setattr(init_mod, "IBM_AUTH_ENABLED", False)
    monkeypatch.setattr(init_mod, "PLATFORM_AUTH_DEV_MODE", False)

    os_client = _fake_os_client()

    with (
        patch("utils.opensearch_utils.setup_opensearch_security", AsyncMock()),
        patch.object(init_mod, "wait_for_opensearch", AsyncMock()),
        patch.object(
            init_mod, "create_index_body", AsyncMock(return_value={"settings": {}, "mappings": {}})
        ),
        patch.object(init_mod, "get_index_name", return_value="documents"),
    ):
        await init_mod.init_index(opensearch_client=os_client)

    # The three indices: documents, knowledge_filters, api_keys.
    created_indices = {
        call.kwargs.get("index") for call in os_client.indices.create.await_args_list
    }
    assert "documents" in created_indices
    assert "knowledge_filters" in created_indices
    assert "api_keys" in created_indices, (
        "api_keys index creation must still run when security setup is skipped"
    )
