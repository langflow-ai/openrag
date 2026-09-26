"""Docling Serve component: a 404 on a task poll is reported as an expired task.

docling-serve deletes a finished task some minutes after its result is first
fetched. When a flow run was replayed after that, the component surfaced a bare
"Client error '404 Not Found' for url .../status/poll/<id>", which hid the real
failure. It now raises an explicit "task not found / expired" error, both on
the first poll and on a poll inside the wait loop (which previously fell
through to a `KeyError` on the 404 body).

`lfx` and docling-core are not in the backend venv, so they are stubbed for the
duration of each test only.
"""

import importlib.util
import sys
import types
from pathlib import Path

import httpx
import pytest

COMPONENT_PATH = (
    Path(__file__).resolve().parents[2] / "custom_components" / "openrag" / "docling_remote.py"
)
BASE_URL = "http://docling:5001/v1"
TASK_ID = "df980024-2298-48f9-84e6-eadc046221cc"


class _BaseFileComponent:
    class BaseFile:  # referenced in annotations only
        pass

    @staticmethod
    def get_base_inputs():
        return []

    @staticmethod
    def get_base_outputs():
        return []


@pytest.fixture
def component(monkeypatch):
    def module(name, **attrs):
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        monkeypatch.setitem(sys.modules, name, mod)
        return mod

    def factory(*args, **kwargs):
        return None

    module("lfx")
    module("lfx.base")
    module("lfx.base.data", BaseFileComponent=_BaseFileComponent)
    module(
        "lfx.inputs",
        IntInput=factory,
        NestedDictInput=factory,
        StrInput=factory,
        TableInput=factory,
    )
    module("lfx.inputs.inputs", FloatInput=factory)
    module("lfx.schema", Data=dict, dotdict=dict)
    module("lfx.utils")
    module("lfx.utils.util", transform_localhost_url=lambda url: url)
    module("docling_core")
    module("docling_core.types")
    module("docling_core.types.doc", DoclingDocument=object)

    spec = importlib.util.spec_from_file_location("_docling_remote_under_test", COMPONENT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)

    instance = object.__new__(mod.DoclingRemoteComponent)
    instance.logs = []
    instance.log = instance.logs.append
    instance.max_poll_timeout = 60
    return instance


def _client(statuses: list[tuple[int, dict]]) -> tuple[httpx.Client, list[str]]:
    seen: list[str] = []
    queue = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_a_missing_task_on_the_first_poll_is_reported_as_expired(component):
    client, seen = _client([(404, {"detail": "Task not found."})])

    with pytest.raises(RuntimeError, match="not found on the Docling Serve server") as exc:
        component._poll_and_fetch_result(client, BASE_URL, TASK_ID)

    assert TASK_ID in str(exc.value)
    assert "expired" in str(exc.value)
    assert seen == [f"/v1/status/poll/{TASK_ID}"]
    assert component.logs and TASK_ID in component.logs[0]


def test_a_task_that_disappears_while_polling_is_reported_as_expired(component):
    client, seen = _client(
        [
            (200, {"task_status": "started"}),
            (404, {"detail": "Task not found."}),
        ]
    )

    with pytest.raises(RuntimeError, match="not found on the Docling Serve server"):
        component._poll_and_fetch_result(client, BASE_URL, TASK_ID)

    assert len(seen) == 2


def test_other_client_errors_while_polling_still_raise_http_errors(component):
    client, _ = _client(
        [
            (200, {"task_status": "started"}),
            (403, {"detail": "Forbidden"}),
        ]
    )

    with pytest.raises(httpx.HTTPStatusError):
        component._poll_and_fetch_result(client, BASE_URL, TASK_ID)
