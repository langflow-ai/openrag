"""The Langflow LLM proxy must never be exposed as a FastMCP tool."""

from mcp_http.server import MCPType, RouteMap, create_mcp_server


def test_langflow_llm_proxy_routes_are_excluded_before_the_v1_tool_catch_all(monkeypatch):
    captured: dict[str, list[RouteMap]] = {}

    def fake_from_fastapi(*, app, name, route_maps, mcp_component_fn):
        captured["route_maps"] = route_maps
        return object()

    monkeypatch.setattr("mcp_http.server.FastMCP.from_fastapi", fake_from_fastapi)
    create_mcp_server(object())

    route_maps = captured["route_maps"]
    excluded = [route_map for route_map in route_maps if route_map.mcp_type is MCPType.EXCLUDE]
    patterns = {route_map.pattern for route_map in excluded}
    assert r"^/v1/models$" in patterns
    assert r"^/v1/chat/completions$|^/v1/embeddings$" in patterns

    catch_all_index = next(index for index, route_map in enumerate(route_maps) if route_map.pattern == r"^/v1/")
    assert all(route_maps.index(route_map) < catch_all_index for route_map in excluded[:3])
