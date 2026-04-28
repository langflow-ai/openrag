import asyncio
import json
import os
from typing import Any

import pytest


OPENRAG_MCP_SERVER_NAME = "lf-starter_project"
LANGFLOW_GLOBAL_VAR_PREFIX = "x-langflow-global-var-"


async def _wait_for_langflow_client(timeout_s: float = 60.0):
    from config.settings import clients

    await clients.initialize()
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        langflow_client = await clients.ensure_langflow_client()
        if langflow_client is not None:
            return langflow_client
        await asyncio.sleep(1.0)
    return None


def _server_name(server: dict[str, Any]) -> str | None:
    return server.get("name") or server.get("server") or server.get("id")


def _extract_server_urls(server_config: dict[str, Any]) -> list[str]:
    urls = []
    url = server_config.get("url")
    if isinstance(url, str):
        urls.append(url)

    args = server_config.get("args", [])
    if isinstance(args, list):
        urls.extend(
            arg
            for arg in args
            if isinstance(arg, str)
            and (arg.startswith("http://") or arg.startswith("https://"))
        )
    return urls


def _extract_server_headers(server_config: dict[str, Any]) -> dict[str, str]:
    headers = {}

    raw_headers = server_config.get("headers")
    if isinstance(raw_headers, dict):
        headers.update(
            {
                str(key): str(value)
                for key, value in raw_headers.items()
                if value is not None
            }
        )

    args = server_config.get("args", [])
    if isinstance(args, list):
        i = 0
        while i < len(args):
            if args[i] == "--headers" and i + 2 < len(args):
                headers[str(args[i + 1])] = str(args[i + 2])
                i += 3
            else:
                i += 1

    return headers


def _assert_no_persisted_langflow_globals(headers: dict[str, str]) -> None:
    persisted_global_headers = [
        key for key in headers if key.lower().startswith(LANGFLOW_GLOBAL_VAR_PREFIX)
    ]
    assert not persisted_global_headers, (
        "MCP server config must not persist Langflow global-var headers: "
        f"{persisted_global_headers}"
    )


@pytest.mark.asyncio
async def test_openrag_mcp_server_url_is_patched_without_persisting_request_globals():
    from config.settings import LANGFLOW_URL
    from services.langflow_mcp_service import LangflowMCPService

    langflow_client = await _wait_for_langflow_client()
    assert langflow_client is not None, (
        "Langflow client not initialized. Provide LANGFLOW_KEY or enable "
        "superuser auto-login for integration tests."
    )

    mcp_service = LangflowMCPService()
    await mcp_service.update_all_mcp_server_urls()

    servers = await mcp_service.list_mcp_servers()
    server_names = [_server_name(server) for server in servers]
    assert OPENRAG_MCP_SERVER_NAME in server_names, (
        f"Expected OpenRAG MCP server {OPENRAG_MCP_SERVER_NAME!r}; "
        f"found {server_names}"
    )

    server_config = await mcp_service.get_mcp_server(OPENRAG_MCP_SERVER_NAME)
    urls = _extract_server_urls(server_config)
    assert urls, f"MCP server has no configured URL: {server_config}"

    expected_base = (LANGFLOW_URL or os.environ.get("LANGFLOW_URL", "")).rstrip("/")
    if expected_base and "localhost" not in expected_base:
        assert any(url.startswith(expected_base) for url in urls), (
            f"MCP server URLs were not rewritten to LANGFLOW_URL={expected_base!r}: "
            f"{urls}"
        )

    _assert_no_persisted_langflow_globals(_extract_server_headers(server_config))


@pytest.mark.asyncio
async def test_loaded_agent_flow_routes_request_globals_into_mcp_headers():
    from config.settings import LANGFLOW_CHAT_FLOW_ID, clients

    langflow_client = await _wait_for_langflow_client()
    assert langflow_client is not None, (
        "Langflow client not initialized. Provide LANGFLOW_KEY or enable "
        "superuser auto-login for integration tests."
    )
    assert LANGFLOW_CHAT_FLOW_ID, "LANGFLOW_CHAT_FLOW_ID is required"

    response = await clients.langflow_request(
        "GET",
        f"/api/v1/flows/{LANGFLOW_CHAT_FLOW_ID}",
    )
    response.raise_for_status()
    flow_text = json.dumps(response.json())

    assert "opensearch_url_ingestion_flow" in flow_text
    assert OPENRAG_MCP_SERVER_NAME in flow_text
    assert "DynamicCreateData-ElAqI" in flow_text
    assert "MCP-k64rA" in flow_text
    assert '"target": "MCP-k64rA"' in flow_text
    assert '"fieldName": "headers"' in flow_text

    for global_var_name in [
        "JWT",
        "OPENAI_API_KEY",
        "OPENSEARCH_URL",
        "OWNER",
        "OWNER_EMAIL",
        "OWNER_NAME",
        "SELECTED_EMBEDDING_MODEL",
        "WATSONX_APIKEY",
        "WATSONX_PROJECT_ID",
        "OPENSEARCH_INDEX_NAME",
        "CONNECTOR_TYPE",
    ]:
        assert f"dynamic_X-Langflow-Global-Var-{global_var_name}" in flow_text
