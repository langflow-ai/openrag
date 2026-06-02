import json
from pathlib import Path


def _load_flow(flow_path: str) -> dict:
    return json.loads(Path(flow_path).read_text(encoding="utf-8"))


def _opensearch_nodes(flow: dict) -> list[dict]:
    return [
        node
        for node in flow["data"]["nodes"]
        if "OpenSearchVectorStoreComponent" in node.get("data", {}).get("type", "")
    ]


def test_opensearch_component_returns_table_search_results():
    code = Path("flows/components/opensearch_multimodal.py").read_text(encoding="utf-8")

    assert "from lfx.schema.dataframe import Table" in code
    assert "def search_documents(self) -> Table:" in code
    assert "return Table(data=raw_list)" in code
    assert 'name="dataframe"' not in code
    assert "def as_dataframe" not in code


def test_embedded_opensearch_nodes_expose_table_search_results():
    for flow_path in (
        "flows/ingestion_flow.json",
        "flows/openrag_nudges.json",
        "flows/openrag_url_mcp.json",
    ):
        flow = _load_flow(flow_path)
        for node in _opensearch_nodes(flow):
            outputs = node["data"]["node"]["outputs"]
            if any(output.get("name") == "component_as_tool" for output in outputs):
                continue

            search_output = next(
                output for output in outputs if output.get("name") == "search_results"
            )
            assert search_output["method"] == "search_documents"
            assert search_output["types"] == ["Table"]
            assert all(output.get("name") != "dataframe" for output in outputs)


def test_nudges_flow_uses_opensearch_search_results_table():
    flow = _load_flow("flows/openrag_nudges.json")
    opensearch_node_ids = {node["id"] for node in _opensearch_nodes(flow)}
    parser_node_ids = {
        node["id"]
        for node in flow["data"]["nodes"]
        if node.get("data", {}).get("type") == "ParserComponent"
    }

    opensearch_to_parser_edges = [
        edge
        for edge in flow["data"]["edges"]
        if edge.get("source") in opensearch_node_ids and edge.get("target") in parser_node_ids
    ]

    assert len(opensearch_to_parser_edges) == 1
    source_handle = opensearch_to_parser_edges[0]["data"]["sourceHandle"]
    assert source_handle["name"] == "search_results"
    assert source_handle["output_types"] == ["Table"]


def test_parser_components_are_not_forked_for_list_data():
    for flow_path in ("flows/openrag_nudges.json", "flows/openrag_url_mcp.json"):
        flow = _load_flow(flow_path)
        parser_node = next(
            node
            for node in flow["data"]["nodes"]
            if node.get("data", {}).get("type") == "ParserComponent"
        )
        code = parser_node["data"]["node"]["template"]["code"]["value"]

        assert "return DataFrame(data=[item.data for item in input_data]), None" not in code
