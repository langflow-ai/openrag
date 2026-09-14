"""A langflowless deployment must not wait for, or call, Langflow at startup.

The Langflow container sits behind a compose profile and is not started by
default, so both the client bootstrap (`AppClients._initialize_langflow_client`)
and the Langflow-only startup steps have to be skipped when nothing in the stack
needs Langflow — otherwise every boot burns the full `wait_for_langflow` retry
budget and then fails.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import AppClients, is_langflow_in_use
from services.startup_orchestrator import _langflow_startup_tasks


class _Cfg:
    def __init__(self, chat: bool, ingest: bool):
        self.agent = type("A", (), {"disable_chat_with_langflow": chat})()
        self.knowledge = type("K", (), {"disable_ingest_with_langflow": ingest})()


@pytest.fixture(autouse=True)
def _no_env_kill_switches(monkeypatch):
    monkeypatch.delenv("DISABLE_CHAT_WITH_LANGFLOW", raising=False)
    monkeypatch.delenv("DISABLE_INGEST_WITH_LANGFLOW", raising=False)


@pytest.mark.parametrize(
    "chat_disabled,ingest_disabled,in_use",
    [
        (True, True, False),  # fully langflowless — the new default
        (True, False, True),  # ingestion still runs flows
        (False, True, True),  # chat still runs flows
        (False, False, True),
    ],
)
def test_is_langflow_in_use_truth_table(chat_disabled, ingest_disabled, in_use):
    """Only when BOTH bypasses are on is Langflow out of the picture."""
    with patch(
        "config.settings.get_openrag_config",
        return_value=_Cfg(chat=chat_disabled, ingest=ingest_disabled),
    ):
        assert is_langflow_in_use() is in_use


def test_env_kill_switch_still_wins(monkeypatch):
    """The env kill switches keep precedence over a config that says otherwise."""
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", "true")
    monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "true")
    with patch("config.settings.get_openrag_config", return_value=_Cfg(chat=False, ingest=False)):
        assert is_langflow_in_use() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("in_use", [False, True])
async def test_client_bootstrap_health_check_follows_the_gate(in_use):
    """wait_for_langflow and the API key it gates run only when Langflow is used.

    LANGFLOW_KEY is pinned empty so the follow-on `ensure_langflow_client` path
    (which mints the key a second time) stays out of the assertions.
    """
    clients = AppClients()
    with (
        patch("config.settings.is_langflow_in_use", return_value=in_use),
        patch("config.settings.LANGFLOW_KEY", ""),
        patch("utils.langflow_utils.wait_for_langflow", new=AsyncMock()) as wait,
        patch("config.settings.get_langflow_api_key", new=AsyncMock()) as get_key,
    ):
        await clients._initialize_langflow_client()

    assert wait.await_count == (1 if in_use else 0)
    assert get_key.await_count == (1 if in_use else 0)
    assert clients.langflow_client is None


def _services() -> dict:
    flows_service = MagicMock()
    flows_service.ensure_flows_exist = AsyncMock()
    flows_service.get_chat_flow_system_prompt = AsyncMock(return_value="")
    flows_service.update_chat_flow_system_prompt = AsyncMock()
    mcp_service = MagicMock()
    mcp_service.update_all_mcp_server_urls = AsyncMock(return_value={})
    return {"flows_service": flows_service, "langflow_mcp_service": mcp_service}


@pytest.mark.asyncio
async def test_startup_tasks_skip_langflow_steps_when_unused():
    """No MCP sync, no flow creation, no global-variable seeding."""
    services = _services()
    with (
        patch("config.settings.is_langflow_in_use", return_value=False),
        patch(
            "api.settings.langflow_sync.ensure_required_langflow_global_variables",
            new=AsyncMock(),
        ) as ensure_globals,
    ):
        await _langflow_startup_tasks(services)

    services["langflow_mcp_service"].update_all_mcp_server_urls.assert_not_awaited()
    services["flows_service"].ensure_flows_exist.assert_not_awaited()
    ensure_globals.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_tasks_run_langflow_steps_when_used():
    """The steps still run for a deployment that does use Langflow."""
    services = _services()
    with (
        patch("config.settings.is_langflow_in_use", return_value=True),
        patch(
            "api.settings.langflow_sync.ensure_required_langflow_global_variables",
            new=AsyncMock(),
        ) as ensure_globals,
    ):
        await _langflow_startup_tasks(services)

    services["langflow_mcp_service"].update_all_mcp_server_urls.assert_awaited_once()
    services["flows_service"].ensure_flows_exist.assert_awaited_once()
    ensure_globals.assert_awaited_once()
