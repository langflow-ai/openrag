"""Unit tests for OpenRAGClient authentication headers and TLS verification."""

import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
import trustme

from openrag_sdk import OpenRAGClient

SETTINGS_BODY = {"agent": {}, "knowledge": {}}


def _capturing_client(sent: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=SETTINGS_BODY)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("header_name", ["X-Api-Key", "x-api-key", "X-API-KEY"])
async def test_extra_headers_key_is_sent_once_and_wins_over_env(
    monkeypatch: pytest.MonkeyPatch, header_name: str
) -> None:
    monkeypatch.setenv("OPENRAG_API_KEY", "env-key")
    sent: list[httpx.Request] = []
    async with _capturing_client(sent) as http:
        client = OpenRAGClient(
            base_url="http://openrag.test",
            extra_headers={"X-Username": "alice", header_name: "header-key"},
            http_client=http,
        )
        await client.settings.get()

    assert sent[0].headers.get_list("x-api-key") == ["header-key"]
    assert sent[0].headers["x-username"] == "alice"


async def test_api_key_is_sent_when_extra_headers_lack_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENRAG_API_KEY", raising=False)
    sent: list[httpx.Request] = []
    async with _capturing_client(sent) as http:
        client = OpenRAGClient(
            api_key="orag_key",
            base_url="http://openrag.test",
            extra_headers={"X-Username": "alice"},
            http_client=http,
        )
        await client.settings.get()

    assert sent[0].headers.get_list("x-api-key") == ["orag_key"]


@pytest.fixture
def private_ca_server(tmp_path):
    """HTTPS server on 127.0.0.1 whose certificate is issued by a private CA."""
    ca = trustme.CA()
    server_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert("127.0.0.1").configure_cert(server_ctx)
    ca_path = tmp_path / "ca.pem"
    ca.cert_pem.write_to_path(str(ca_path))

    body = json.dumps(SETTINGS_BODY).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = server_ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"https://127.0.0.1:{server.server_address[1]}", str(ca_path)
    server.shutdown()
    server.server_close()


async def test_verify_with_ca_path_trusts_private_ca(
    private_ca_server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    url, ca_path = private_ca_server

    client = OpenRAGClient(api_key="k", base_url=url, verify=ca_path)
    try:
        settings = await client.settings.get()
    finally:
        await client.close()
    assert settings.agent is not None


async def test_default_verify_rejects_private_ca(
    private_ca_server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    url, _ = private_ca_server

    client = OpenRAGClient(api_key="k", base_url=url)
    try:
        with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
            await client.settings.get()
    finally:
        await client.close()


async def test_verify_cannot_be_combined_with_http_client() -> None:
    async with httpx.AsyncClient() as http:
        with pytest.raises(ValueError, match="http_client"):
            OpenRAGClient(api_key="k", http_client=http, verify=False)
