"""Regression coverage for `_update_provider_components_locked`.

Two bugs, found while rebasing the OpenAI custom base-URL PR (#2063) onto
current main:

1. A mis-indented refactor (upstream commit a1930ba, "add upgrade flows
   functionality") nested this entire method's body inside the
   `wrap_node_update` closure, after its `return None` - making it dead
   code. `node_tasks` stayed empty no matter what, so the method always
   short-circuited to the "No compatible components found... (skipped)"
   response and never patched a single flow component, for any provider.

2. Even once reachable, the `is_new_flow` branch (current default flow
   layout - a single generic Embedding Model / Language Model component)
   only called `_enable_model_in_langflow` (registers the model name in
   Langflow's catalog) and never `_update_component_fields` - so the
   component's api_key/api_base fields (which now always point at the
   OpenRAG LLM proxy, per the `proxy_fields` mapping) were never applied
   to the node itself.

These tests build a minimal "new flow" (one generic embedding node, one
generic LLM node, one Agent node) and assert the PATCH actually fires and
the api_base field is set - proving both bugs are fixed together.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.settings import OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME  # noqa: E402
from services.flows_service import FlowsService  # noqa: E402


def _generic_embedding_node():
    return {
        "data": {
            "node": {
                "display_name": OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME,
                "template": {
                    "api_base": {"value": "", "load_from_db": False},
                },
            }
        }
    }


def _flow_data_with_one_embedding_node():
    return {
        "id": "flow-1",
        "name": "Retrieval Flow",
        "data": {"nodes": [_generic_embedding_node()]},
    }


def _make_langflow_request_mock(flow_data):
    async def _mock(method, url, json=None, **kwargs):
        if method == "GET" and url.startswith("/api/v1/flows/"):
            return MagicMock(status_code=200, json=MagicMock(return_value=flow_data))
        if method == "GET" and url == "/api/v1/models/enabled_models":
            return MagicMock(status_code=200, json=MagicMock(return_value={"enabled_models": {}}))
        if method == "POST" and url == "/api/v1/models/enabled_models":
            return MagicMock(status_code=200)
        if method == "PATCH" and url.startswith("/api/v1/flows/"):
            return MagicMock(status_code=200, json=MagicMock(return_value={}))
        raise AssertionError(f"Unexpected langflow_request call: {method} {url}")

    return _mock


@pytest.fixture(autouse=True)
def _isolate_flow_locking(monkeypatch):
    """_update_provider_components_locked assumes the caller already holds
    the flow lock and calls _unlock_flow/_lock_flow around the PATCH;
    no-op those so this unit test doesn't need the real locking machinery."""
    monkeypatch.setattr(FlowsService, "_unlock_flow", AsyncMock())
    monkeypatch.setattr(FlowsService, "_lock_flow", AsyncMock())
    monkeypatch.setattr(
        "services.flows_service.get_openrag_config",
        lambda: MagicMock(knowledge=MagicMock(disable_ingest_with_langflow=False)),
    )


@pytest.mark.asyncio
async def test_new_flow_embedding_component_is_actually_patched(monkeypatch):
    """Bug 1 regression: the method must not always short-circuit to
    "skipped" - it must reach the node_tasks loop and PATCH the flow."""
    flow_data = _flow_data_with_one_embedding_node()
    monkeypatch.setattr(
        "services.flows_service.clients.langflow_request",
        _make_langflow_request_mock(flow_data),
    )

    service = FlowsService()
    result = await service._update_provider_components_locked(
        {"name": "Retrieval Flow", "flow_id": "flow-1"},
        "openai",
        embedding_model="text-embedding-3-small",
    )

    assert result["success"] is True
    assert "skipped" not in result["message"]


@pytest.mark.asyncio
async def test_new_flow_embedding_component_gets_api_base_mapped(monkeypatch):
    """Bug 2 regression: the is_new_flow branch must call
    _update_component_fields, not just _enable_model_in_langflow - proven
    by the api_base field actually being wired to the OpenRAG LLM proxy."""
    flow_data = _flow_data_with_one_embedding_node()
    monkeypatch.setattr(
        "services.flows_service.clients.langflow_request",
        _make_langflow_request_mock(flow_data),
    )

    service = FlowsService()
    await service._update_provider_components_locked(
        {"name": "Retrieval Flow", "flow_id": "flow-1"},
        "openai",
        embedding_model="text-embedding-3-small",
    )

    node = flow_data["data"]["nodes"][0]
    template = node["data"]["node"]["template"]
    assert template["api_base"]["value"] == "OPENRAG_LLM_BASE_URL"
    assert template["api_base"]["load_from_db"] is True
