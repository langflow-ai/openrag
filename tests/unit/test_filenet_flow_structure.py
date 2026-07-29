"""Structural guards for the FileNet P8 node in the agent flow.

Asserts that flows/openrag_agent.json carries the FileNetSearch node wired as
an Agent tool, that its embedded component code stays in sync with
flows/components/filenet_retrieve_window.py (the repo convention: the .py file
is the source of truth, the flow embeds a copy), and that the agent system
prompt stays byte-identical between the flow JSON and the config_manager
default (settings saves overwrite the flow prompt from config, so drift means
deployed behavior diverges from the shipped flow).
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FLOW_PATH = REPO_ROOT / "flows" / "openrag_agent.json"
COMPONENT_PATH = REPO_ROOT / "flows" / "components" / "filenet_retrieve_window.py"

NODE_ID = "FileNetSearch-P8fn1"
AGENT_ID = "Agent-Nfw7u"


def _load_flow() -> dict:
    return json.loads(FLOW_PATH.read_text())


def _filenet_node(flow: dict) -> dict:
    matches = [n for n in flow["data"]["nodes"] if n["id"] == NODE_ID]
    assert len(matches) == 1, "FileNetSearch node missing from openrag_agent.json"
    return matches[0]


def test_filenet_node_exists_as_tool():
    node = _filenet_node(_load_flow())
    node_def = node["data"]["node"]
    assert node_def["tool_mode"] is True
    outputs = node_def["outputs"]
    assert any(o.get("name") == "component_as_tool" and o.get("types") == ["Tool"] for o in outputs)


def test_filenet_edge_targets_agent_tools():
    flow = _load_flow()
    edges = [e for e in flow["data"]["edges"] if e.get("source") == NODE_ID]
    assert len(edges) == 1, "FileNetSearch -> Agent edge missing"
    edge = edges[0]
    assert edge["target"] == AGENT_ID
    assert edge["data"]["sourceHandle"]["name"] == "component_as_tool"
    assert edge["data"]["targetHandle"]["fieldName"] == "tools"
    # The flat (œ-encoded) handles must agree with the structured ones.
    assert "FileNetSearch" in edge["sourceHandle"]
    assert "tools" in edge["targetHandle"]


def test_embedded_component_code_matches_source_file():
    """flows/components/filenet_retrieve_window.py is the source of truth;
    the flow embeds a copy (sync via scripts/update_flow_components.py)."""
    node = _filenet_node(_load_flow())
    embedded = node["data"]["node"]["template"]["code"]["value"]
    assert embedded == COMPONENT_PATH.read_text()


def test_tools_metadata_action_teaches_the_agent():
    node = _filenet_node(_load_flow())
    actions = node["data"]["node"]["template"]["tools_metadata"]["value"]
    assert len(actions) == 1
    action = actions[0]
    assert action["name"] == "filenet_document_search"
    assert action["status"] is True
    assert "search_term" in action["args"]
    # The description is the non-user-overridable guidance channel.
    assert "FileNet" in action["description"]
    assert "non-empty" in action["description"]


def test_pinned_defaults_match_assessment():
    node = _filenet_node(_load_flow())
    template = node["data"]["node"]["template"]
    assert template["mcp_server_name"]["value"] == "filenet-p8"
    assert template["document_class"]["value"] == "Document"
    assert template["top_k"]["value"] == 5
    assert template["snippet_char_cap"]["value"] == 2000
    # Only search_term is agent-controlled.
    tool_mode_fields = [
        name
        for name, entry in template.items()
        if isinstance(entry, dict) and entry.get("tool_mode") is True
    ]
    assert tool_mode_fields == ["search_term"]


def test_system_prompt_mentions_filenet_in_flow_and_config():
    flow = _load_flow()
    agent = [n for n in flow["data"]["nodes"] if n["id"] == AGENT_ID][0]
    flow_prompt = agent["data"]["node"]["template"]["system_prompt"]["value"]
    assert "FileNet P8 Search Tool (filenet_document_search)" in flow_prompt
    assert "never call it with an empty search_term" in flow_prompt

    from config.config_manager import AgentConfig

    config_prompt = AgentConfig().system_prompt
    assert config_prompt == flow_prompt, (
        "Agent system prompt drifted between flows/openrag_agent.json and "
        "config_manager.AgentConfig — settings saves push the config value "
        "into the flow, so these must stay byte-identical."
    )
