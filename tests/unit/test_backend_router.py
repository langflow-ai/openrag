"""Tests for the standalone allowlisted Langflow proxy router."""

import pytest
from fastapi.testclient import TestClient

from app import router_app
from config import settings

# --- run-mode-dependent enable default ---------------------------------------


@pytest.mark.parametrize(
    "run_mode, expected",
    [
        ("", "false"),  # unset -> default oss path
        ("oss", "false"),
        ("saas", "true"),
        ("SaaS", "true"),
        ("on_prem", "false"),
        ("unknown-mode", "false"),
    ],
)
def test_enable_default_resolves_from_run_mode(monkeypatch, run_mode, expected):
    if run_mode:
        monkeypatch.setenv("OPENRAG_RUN_MODE", run_mode)
    else:
        monkeypatch.delenv("OPENRAG_RUN_MODE", raising=False)
    assert settings._resolve_backend_router_enable_default() == expected


# --- callback URL selection -------------------------------------------------


def test_callback_url_uses_router_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "OPENRAG_BACKEND_ROUTER_ENABLE", True)
    monkeypatch.setattr(settings, "OPENRAG_BACKEND_ROUTER_URL", "http://router:8100")
    assert settings.get_ingest_callback_url() == "http://router:8100/internal/ingest/chunks"


def test_callback_url_uses_backend_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "OPENRAG_BACKEND_ROUTER_ENABLE", False)
    monkeypatch.setattr(settings, "OPENRAG_BACKEND_INTERNAL_URL", "http://be:8000")
    assert settings.get_ingest_callback_url() == "http://be:8000/internal/ingest/chunks"


def test_llm_base_url_uses_router_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "OPENRAG_BACKEND_ROUTER_ENABLE", True)
    monkeypatch.setattr(settings, "OPENRAG_BACKEND_ROUTER_URL", "http://router:8100")
    assert settings.get_langflow_llm_base_url() == "http://router:8100"


def test_llm_base_url_uses_backend_when_router_disabled(monkeypatch):
    monkeypatch.delenv("OPENRAG_LLM_PROXY_URL", raising=False)
    monkeypatch.setattr(settings, "OPENRAG_BACKEND_ROUTER_ENABLE", False)
    monkeypatch.setattr(settings, "OPENRAG_BACKEND_INTERNAL_URL", "http://be:8000")
    assert settings.get_langflow_llm_base_url() == "http://be:8000/v1"


def test_llm_base_url_override_wins_over_router(monkeypatch):
    monkeypatch.setenv("OPENRAG_LLM_PROXY_URL", "https://llm-proxy.example/v1/")
    monkeypatch.setattr(settings, "OPENRAG_BACKEND_ROUTER_ENABLE", True)
    assert settings.get_langflow_llm_base_url() == "https://llm-proxy.example/v1"


def test_router_url_derives_backend_host_on_router_port(monkeypatch):
    monkeypatch.setattr(settings, "OPENRAG_BACKEND_INTERNAL_URL", "http://openrag-be:8000")
    monkeypatch.setattr(settings, "OPENRAG_BACKEND_ROUTER_PORT", 8100)
    assert settings._derive_router_url() == "http://openrag-be:8100"


# --- proxy behaviour --------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code, content, headers):
        self.status_code = status_code
        self.content = content
        self.headers = headers


class _FakeClient:
    """Async-context-manager stand-in for httpx.AsyncClient capturing the call."""

    def __init__(self, captured):
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, content=None, headers=None):
        self._captured["url"] = url
        self._captured["content"] = content
        self._captured["headers"] = headers
        return _FakeResponse(200, b'{"status":"ok"}', {"content-type": "application/json"})


class _FakeStreamingResponse(_FakeResponse):
    async def aiter_raw(self):
        yield self.content

    async def aclose(self):
        pass


class _FakeLlmClient:
    def __init__(self, captured):
        self._captured = captured

    def build_request(self, method, url, content=None, headers=None, params=None):
        self._captured.update(
            method=method, url=url, content=content, headers=headers, params=dict(params or {})
        )
        return object()

    async def send(self, request, stream=False):
        self._captured["stream"] = stream
        return _FakeStreamingResponse(
            200, b'{"object":"list","data":[]}', {"content-type": "application/json"}
        )

    async def aclose(self):
        pass


def test_proxy_forwards_only_allowlisted_headers(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(router_app.httpx, "AsyncClient", lambda *a, **k: _FakeClient(captured))

    client = TestClient(router_app.create_router_app())
    resp = client.post(
        "/internal/ingest/chunks",
        content=b'{"ingest_run_id":"run-1","chunks":[]}',
        headers={
            "Authorization": "Bearer tok",
            "X-OpenRAG-Ingest-Token": "tok2",
            "Content-Type": "application/json",
            "X-Evil": "should-be-dropped",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    # Forwarded to the co-located backend over LOOPBACK (not the service name),
    # with the original body.
    assert captured["url"] == router_app._UPSTREAM_URL
    assert captured["url"].startswith("http://127.0.0.1:8000")
    assert captured["url"].endswith(settings.INGEST_CALLBACK_PATH)
    assert captured["content"] == b'{"ingest_run_id":"run-1","chunks":[]}'
    fwd = {k.lower() for k in captured["headers"]}
    assert "authorization" in fwd
    assert "x-openrag-ingest-token" in fwd
    assert "x-evil" not in fwd


def test_proxy_returns_502_when_upstream_unreachable(monkeypatch):
    class _BoomClient(_FakeClient):
        async def post(self, *a, **k):
            raise router_app.httpx.ConnectError("nope")

    monkeypatch.setattr(router_app.httpx, "AsyncClient", lambda *a, **k: _BoomClient({}))
    client = TestClient(router_app.create_router_app())
    resp = client.post("/internal/ingest/chunks", content=b"{}")
    assert resp.status_code == 502


def test_llm_proxy_forwards_only_allowlisted_headers_and_maps_private_path(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(router_app.httpx, "AsyncClient", lambda *a, **k: _FakeLlmClient(captured))

    client = TestClient(router_app.create_router_app())
    resp = client.post(
        "/embeddings?trace=1",
        content=b'{"model":"text-embedding-3-small","input":"hello"}',
        headers={
            "Authorization": "Bearer hop-token",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Evil": "should-be-dropped",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {"object": "list", "data": []}
    assert captured["url"] == f"{router_app.OPENRAG_BACKEND_ROUTER_UPSTREAM_URL}/v1/embeddings"
    assert captured["params"] == {"trace": "1"}
    assert captured["stream"] is True
    forwarded = {key.lower() for key in captured["headers"]}
    assert {"authorization", "content-type", "accept"} <= forwarded
    assert "x-evil" not in forwarded


def test_router_exposes_only_allowlisted_paths_and_health():
    client = TestClient(router_app.create_router_app())
    assert client.get("/health").status_code == 200
    # No arbitrary proxying, and FastMCP's streamable HTTP endpoint is not
    # exposed by this separate router app.
    assert client.get("/some/other/path").status_code == 404
    assert client.get("/mcp").status_code == 404
    assert client.get("/v1/embeddings").status_code == 404
    assert client.get("/v1/anything-else").status_code == 404
    # Callback is POST-only.
    assert client.get("/internal/ingest/chunks").status_code == 405
