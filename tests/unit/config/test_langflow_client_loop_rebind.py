"""Tests for AppClients.rebind_langflow_http_client().

Regression cover for "RuntimeError: Event loop is closed" on the first
Langflow request of a boot: `clients.initialize()` runs inside
`asyncio.run(create_app())` (main.py), which leaves keep-alive connections in
the shared httpx pool bound to a loop that is closed before uvicorn starts.
"""

import asyncio

import httpx
import pytest

from config.settings import AppClients


def _make_clients_bound_to_a_dead_loop() -> AppClients:
    """Build an AppClients whose Langflow client was created on a closed loop."""
    clients = AppClients()

    async def _init():
        clients.langflow_http_client = clients._new_langflow_http_client()
        clients._langflow_http_client_loop = asyncio.get_running_loop()

    # asyncio.run() closes the loop on exit — exactly what main.py does.
    asyncio.run(_init())
    return clients


def test_rebind_replaces_client_created_on_a_closed_loop():
    clients = _make_clients_bound_to_a_dead_loop()
    stale = clients.langflow_http_client
    dead_loop = clients._langflow_http_client_loop
    assert dead_loop.is_closed()

    async def _startup():
        replaced = await clients.rebind_langflow_http_client()
        return replaced, asyncio.get_running_loop()

    replaced, live_loop = asyncio.run(_startup())

    assert replaced is True
    assert clients.langflow_http_client is not stale
    assert clients._langflow_http_client_loop is live_loop


def test_rebind_preserves_client_configuration():
    clients = _make_clients_bound_to_a_dead_loop()
    stale = clients.langflow_http_client

    asyncio.run(clients.rebind_langflow_http_client())

    fresh = clients.langflow_http_client
    assert fresh.base_url == stale.base_url
    assert fresh.timeout == stale.timeout


@pytest.mark.asyncio
async def test_rebind_is_a_noop_on_the_owning_loop():
    """A client created on the live loop must not be churned on every call."""
    clients = AppClients()
    clients.langflow_http_client = clients._new_langflow_http_client()
    clients._langflow_http_client_loop = asyncio.get_running_loop()
    original = clients.langflow_http_client

    assert await clients.rebind_langflow_http_client() is False
    assert clients.langflow_http_client is original

    await clients.langflow_http_client.aclose()


@pytest.mark.asyncio
async def test_rebind_is_a_noop_when_no_client_exists():
    clients = AppClients()
    assert clients.langflow_http_client is None

    assert await clients.rebind_langflow_http_client() is False
    assert clients.langflow_http_client is None


@pytest.mark.asyncio
async def test_rebind_survives_a_stale_client_that_fails_to_close(monkeypatch):
    """Closing a pool owned by a dead loop can raise; that must not propagate."""
    clients = AppClients()

    class _ExplodingClient(httpx.AsyncClient):
        async def aclose(self):
            raise RuntimeError("Event loop is closed")

    clients.langflow_http_client = _ExplodingClient()
    clients._langflow_http_client_loop = object()  # sentinel: not the live loop

    assert await clients.rebind_langflow_http_client() is True
    assert isinstance(clients.langflow_http_client, httpx.AsyncClient)
    assert not isinstance(clients.langflow_http_client, _ExplodingClient)

    await clients.langflow_http_client.aclose()


def test_reused_pooled_connection_from_a_dead_loop_fails_without_rebind():
    """Demonstrates the underlying failure the rebind exists to prevent."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread

    class _Handler(BaseHTTPRequestHandler):
        # HTTP/1.0 (the default) closes the connection after each response, so
        # nothing would stay in the pool and the bug would not reproduce.
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    clients = AppClients()

    async def _init():
        clients.langflow_http_client = httpx.AsyncClient(base_url=base_url)
        clients._langflow_http_client_loop = asyncio.get_running_loop()
        # Populates the pool with a keep-alive connection bound to this loop.
        assert (await clients.langflow_http_client.get("/health")).status_code == 200

    asyncio.run(_init())

    async def _use_stale():
        return await clients.langflow_http_client.get("/health")

    with pytest.raises(RuntimeError, match="Event loop is closed"):
        asyncio.run(_use_stale())

    # Same sequence, but with the rebind the live loop gets a usable client.
    async def _rebind_then_use():
        # _new_langflow_http_client() would point at the real LANGFLOW_URL, so
        # exercise the rebind decision and rebuild against the stub server.
        assert clients._langflow_http_client_loop.is_closed()
        await clients.rebind_langflow_http_client()
        clients.langflow_http_client = httpx.AsyncClient(base_url=base_url)
        response = await clients.langflow_http_client.get("/health")
        await clients.langflow_http_client.aclose()
        return response

    assert asyncio.run(_rebind_then_use()).status_code == 200
    server.shutdown()
