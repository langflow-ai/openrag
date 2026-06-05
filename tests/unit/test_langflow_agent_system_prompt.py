import json
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest


def _load_flow(flow_path: str) -> dict:
    """Load a Langflow flow JSON file from the given path."""
    return json.loads(Path(flow_path).read_text(encoding="utf-8"))


def _find_node_by_display_name(flow: dict, display_name: str):
    """Return the first flow node whose display_name matches, or None."""
    return next(
        (
            node
            for node in flow["data"]["nodes"]
            if node.get("data", {}).get("node", {}).get("display_name") == display_name
        ),
        None,
    )


def test_agent_flow_has_agent_node_with_system_prompt():
    """The Agent node must exist in openrag_agent.json and expose a system_prompt field."""
    flow = _load_flow("flows/openrag_agent.json")
    agent_node = _find_node_by_display_name(flow, "Agent")

    assert agent_node is not None, "No node with display_name='Agent' found in openrag_agent.json"
    template = agent_node.get("data", {}).get("node", {}).get("template", {})
    assert "system_prompt" in template, "Agent node does not have a system_prompt field in its template"


@pytest.mark.asyncio
async def test_update_chat_flow_system_prompt_updates_agent_node(monkeypatch):
    """update_chat_flow_system_prompt must write the new value into the Agent node's system_prompt field."""
    from services.flows_service import FlowsService

    get_response = MagicMock(status_code=200)
    get_response.json.return_value = _load_flow("flows/openrag_agent.json")
    patch_response = MagicMock(status_code=200)

    request = AsyncMock(side_effect=[get_response, patch_response])
    monkeypatch.setattr("services.flows_service.LANGFLOW_CHAT_FLOW_ID", "test-flow-id")
    monkeypatch.setattr("services.flows_service.clients.langflow_request", request)

    await FlowsService().update_chat_flow_system_prompt("updated system prompt for testing purposes")

    sent_flow = request.call_args_list[1].kwargs["json"]
    agent_node = _find_node_by_display_name(sent_flow, "Agent")
    assert agent_node is not None, "Agent node missing from PATCHed flow data"
    assert agent_node["data"]["node"]["template"]["system_prompt"]["value"] == "updated system prompt for testing purposes"
