"""The MCP search tool is generated from POST /v1/search and exposes `datasets`."""

import pytest
from fastapi import FastAPI

from api.v1 import search as v1_search
from mcp_http.server import create_mcp_server


async def _search_tool():
    app = FastAPI()
    app.add_api_route("/v1/search", v1_search.search_endpoint, methods=["POST"])
    server = create_mcp_server(app)
    tools = await server.list_tools()
    return next(tool for tool in tools if tool.name == "openrag_search")


@pytest.mark.asyncio
async def test_generated_tool_schema_exposes_datasets():
    tool = await _search_tool()

    properties = tool.parameters["properties"]
    assert "datasets" in properties
    assert "query" in tool.parameters["required"]
    assert "datasets" not in tool.parameters.get("required", [])
    kinds = {option.get("type") for option in properties["datasets"]["anyOf"]}
    assert {"array", "string"} <= kinds


@pytest.mark.asyncio
async def test_description_explains_selection_and_the_result_dataset_field():
    tool = await _search_tool()

    description = tool.description
    assert "datasets" in description
    assert "`dataset`" in description
    assert "[]" in description
    assert "filters.datasets" in description
