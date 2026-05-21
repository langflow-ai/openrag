import json
from pathlib import Path


def _parser_component_code(flow_path: str) -> str:
    flow = json.loads(Path(flow_path).read_text(encoding="utf-8"))
    parser_node = next(
        node
        for node in flow["data"]["nodes"]
        if node.get("data", {}).get("type") == "ParserComponent"
    )
    return parser_node["data"]["node"]["template"]["code"]["value"]


def test_parser_components_accept_list_data_inputs():
    for flow_path in ("flows/openrag_nudges.json", "flows/openrag_url_mcp.json"):
        code = _parser_component_code(flow_path)
        assert "List of Data objects is not supported" not in code
        assert "return DataFrame(data=[item.data for item in input_data]), None" in code
