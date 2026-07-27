"""Unit tests for the FileNet P8 MCP sidecar entry point pure helpers.

The sidecar module (sidecars/filenet_mcp/server.py) defers all IBM imports
into main(), so it is importable — and its validation/auth/diagnostics
helpers testable — without the IBM package installed.
"""

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

_SERVER_PATH = (
    Path(__file__).resolve().parents[3] / "sidecars" / "filenet_mcp" / "server.py"
)

_spec = importlib.util.spec_from_file_location("filenet_mcp_server_under_test", _SERVER_PATH)
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


VALID_ENV = {
    "SERVER_URL": "https://cpe.example.com/content-services-graphql/graphql",
    "OBJECT_STORE": "FNOS1DS",
    "USERNAME": "svc-openrag",
    "PASSWORD": "secret",
}


# ---------------------------------------------------------------------------
# validate_environment
# ---------------------------------------------------------------------------


def test_validate_environment_accepts_valid_config():
    assert server.validate_environment(VALID_ENV) == []


@pytest.mark.parametrize("missing", ["SERVER_URL", "OBJECT_STORE", "USERNAME", "PASSWORD"])
def test_validate_environment_reports_each_missing_var(missing):
    env = {k: v for k, v in VALID_ENV.items() if k != missing}
    errors = server.validate_environment(env)
    assert len(errors) == 1
    assert missing in errors[0]


def test_validate_environment_whitespace_counts_as_missing():
    env = dict(VALID_ENV, PASSWORD="   ")
    errors = server.validate_environment(env)
    assert any("PASSWORD" in e for e in errors)


def test_validate_environment_rejects_trailing_slash_server_url():
    """A trailing slash silently turns every text fetch into Mode B upstream."""
    env = dict(VALID_ENV, SERVER_URL=VALID_ENV["SERVER_URL"] + "/")
    errors = server.validate_environment(env)
    assert any("trailing slash" in e for e in errors)


def test_validate_environment_rejects_non_http_server_url():
    env = dict(VALID_ENV, SERVER_URL="cpe.example.com/graphql")
    errors = server.validate_environment(env)
    assert any("http://" in e for e in errors)


def test_validate_environment_reports_all_errors_at_once():
    env = {"SERVER_URL": "https://cpe.example.com/graphql/"}
    errors = server.validate_environment(env)
    # 3 missing vars + trailing slash
    assert len(errors) == 4


# ---------------------------------------------------------------------------
# get_port / resolve_verify
# ---------------------------------------------------------------------------


def test_get_port_default():
    assert server.get_port({}) == server.DEFAULT_PORT


def test_get_port_valid():
    assert server.get_port({"FILENET_MCP_PORT": "9099"}) == 9099


@pytest.mark.parametrize("raw", ["not-a-port", "-1", "0", "70000", "80.5"])
def test_get_port_invalid_falls_back(raw):
    assert server.get_port({"FILENET_MCP_PORT": raw}) == server.DEFAULT_PORT


@pytest.mark.parametrize("raw", ["false", "0", "no", "off", "FALSE"])
def test_resolve_verify_false_values(raw):
    assert server.resolve_verify({"SSL_ENABLED": raw}) is False


@pytest.mark.parametrize("env", [{}, {"SSL_ENABLED": "true"}, {"SSL_ENABLED": ""}])
def test_resolve_verify_true_values(env):
    assert server.resolve_verify(env) is True


def test_resolve_verify_ca_bundle_path_passthrough():
    assert server.resolve_verify({"SSL_ENABLED": "/etc/ssl/ca.pem"}) == "/etc/ssl/ca.pem"


# ---------------------------------------------------------------------------
# is_request_authorized
# ---------------------------------------------------------------------------


def test_auth_disabled_when_no_token_configured():
    assert server.is_request_authorized(None, "") is True
    assert server.is_request_authorized("Bearer anything", "") is True


def test_auth_rejects_missing_header():
    assert server.is_request_authorized(None, "tok") is False
    assert server.is_request_authorized("", "tok") is False


def test_auth_rejects_wrong_scheme():
    assert server.is_request_authorized("Basic dG9rOnRvaw==", "tok") is False


def test_auth_rejects_wrong_token():
    assert server.is_request_authorized("Bearer wrong", "tok") is False


def test_auth_accepts_matching_bearer_token_case_insensitive_scheme():
    assert server.is_request_authorized("Bearer tok", "tok") is True
    assert server.is_request_authorized("bearer tok", "tok") is True


# ---------------------------------------------------------------------------
# run_cpe_diagnostics
# ---------------------------------------------------------------------------


def _response(status_code=200, json_data=None, json_error=None):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = json_data
    return response


def _client(*responses, side_effect=None):
    client = AsyncMock(spec=httpx.AsyncClient)
    if side_effect is not None:
        client.post.side_effect = side_effect
    else:
        client.post.side_effect = list(responses)
    return client


_TXE_OK = {"data": {"classDescription": {"id": "{63BC...}", "symbolicName": "TxeTextExtractAnnotation"}}}
_CBR_OK = {"data": {"classDescription": {"symbolicName": "Document", "isCBREnabled": True}}}


async def _run(client):
    return await server.run_cpe_diagnostics(
        server_url=VALID_ENV["SERVER_URL"],
        object_store=VALID_ENV["OBJECT_STORE"],
        username=VALID_ENV["USERNAME"],
        password=VALID_ENV["PASSWORD"],
        client=client,
    )


@pytest.mark.asyncio
async def test_diagnostics_healthy():
    result = await _run(_client(_response(200, _TXE_OK), _response(200, _CBR_OK)))
    assert result["cpe_reachable"] is True
    assert result["txe_annotation_class_present"] is True
    assert result["cbr_enabled"] is True
    assert result["errors"] == []
    assert result["object_store"] == "FNOS1DS"


@pytest.mark.asyncio
async def test_diagnostics_txe_class_absent():
    """TXE add-on not deployed: classDescription resolves to null."""
    txe_missing = {"data": {"classDescription": None}}
    result = await _run(_client(_response(200, txe_missing), _response(200, _CBR_OK)))
    assert result["cpe_reachable"] is True
    assert result["txe_annotation_class_present"] is False


@pytest.mark.asyncio
async def test_diagnostics_txe_graphql_errors_treated_as_absent():
    txe_err = {"errors": [{"message": "Unknown class TxeTextExtractAnnotation"}]}
    result = await _run(_client(_response(200, txe_err), _response(200, _CBR_OK)))
    assert result["txe_annotation_class_present"] is False
    assert any("TXE class probe" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_diagnostics_cbr_disabled():
    cbr_off = {"data": {"classDescription": {"symbolicName": "Document", "isCBREnabled": False}}}
    result = await _run(_client(_response(200, _TXE_OK), _response(200, cbr_off)))
    assert result["cbr_enabled"] is False


@pytest.mark.asyncio
async def test_diagnostics_auth_failure_401():
    """A 401 must surface loudly — upstream degrades it to empty success."""
    result = await _run(_client(_response(401, {})))
    assert result["cpe_reachable"] is False
    assert result["txe_annotation_class_present"] is None
    assert any("401" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_diagnostics_cpe_unreachable():
    result = await _run(_client(side_effect=httpx.ConnectError("connection refused")))
    assert result["cpe_reachable"] is False
    assert any("Failed to reach CPE" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_diagnostics_cbr_probe_failure_keeps_txe_result():
    result = await _run(
        _client(side_effect=[_response(200, _TXE_OK), httpx.ReadTimeout("timed out")])
    )
    assert result["cpe_reachable"] is True
    assert result["txe_annotation_class_present"] is True
    assert result["cbr_enabled"] is None
    assert any("CBR flag probe" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_diagnostics_non_json_body_never_raises():
    bad = _response(200, json_error=ValueError("not json"))
    result = await _run(_client(bad, _response(200, _CBR_OK)))
    assert result["cpe_reachable"] is True
    assert result["txe_annotation_class_present"] is None
    assert any("non-JSON" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_diagnostics_non_object_json_never_raises():
    result = await _run(_client(_response(200, ["not", "an", "object"]), _response(200, _CBR_OK)))
    assert result["cpe_reachable"] is True
    assert any("non-object" in e for e in result["errors"])
