"""Tests for the image-local Langflow direct base-path ASGI wrapper."""

import asyncio
import importlib.util
from pathlib import Path


def load_wrapper_module():
    script = Path(__file__).parents[2] / "scripts" / "langflow-base-path.py"
    spec = importlib.util.spec_from_file_location("langflow_base_path", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(app, scope):
    received_scopes = []
    sent_events = []

    async def inner(received_scope, receive, send):
        received_scopes.append(received_scope)
        await send({"type": "http.response.start", "status": 204, "headers": []})

    async def receive():
        return {"type": "http.request"}

    async def send(event):
        sent_events.append(event)

    async def run():
        await app(inner)(scope, receive, send)

    asyncio.run(run())
    return received_scopes, sent_events


def test_direct_base_path_strips_prefix_and_sets_asgi_root_path():
    wrapper = load_wrapper_module().DirectBasePathApp
    scope = {
        "type": "http",
        "path": "/langflow/api/v1/flows",
        "raw_path": b"/langflow/api/v1/flows",
        "root_path": "",
    }

    scopes, events = invoke(lambda inner: wrapper(inner, "/langflow"), scope)

    assert scopes == [
        {
            "type": "http",
            "path": "/api/v1/flows",
            "raw_path": b"/api/v1/flows",
            "root_path": "/langflow",
        }
    ]
    assert events[0]["status"] == 204
    assert scope["path"] == "/langflow/api/v1/flows"


def test_direct_base_path_keeps_existing_root_requests_working():
    wrapper = load_wrapper_module().DirectBasePathApp
    scope = {"type": "http", "path": "/health", "root_path": ""}

    scopes, _ = invoke(lambda inner: wrapper(inner, "/langflow"), scope)

    assert scopes == [scope]
