"""`AppClients.langflow_request` retries only what is safe to repeat.

Regression: a folder ingest failed on a real 502 from the embedding endpoint,
Langflow answered the flow run with 500, and the backend replayed
`POST /api/v1/run/{flow}`. The replay re-ran the Docling component against a
task docling-serve had already deleted, and its 404 replaced the real error.
"""

import httpx
import pytest

import config.settings as settings
from config.settings import AppClients

RUN_ENDPOINT = "/api/v1/run/ingest-flow"


class _FakeClient:
    """Replays a scripted sequence of responses or transport errors."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, str]] = []

    async def request(self, *, method, url, headers, **kwargs):
        self.calls.append((method, url))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome, request=httpx.Request(method, url))


@pytest.fixture
def clients(monkeypatch):
    async def api_key(force_regenerate: bool = False):
        return "lf-key"

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(settings, "get_langflow_api_key", api_key)
    monkeypatch.setattr(settings, "LANGFLOW_REQUEST_RETRIES", 2)
    monkeypatch.setattr(settings.asyncio, "sleep", no_sleep)
    return AppClients()


def _install(clients, monkeypatch, outcomes) -> _FakeClient:
    fake = _FakeClient(outcomes)
    monkeypatch.setattr(clients, "_ensure_langflow_http_client", lambda: fake)
    return fake


def _request_error(cls):
    return cls("boom", request=httpx.Request("POST", "http://langflow"))


@pytest.mark.asyncio
async def test_a_failed_flow_run_is_not_replayed(clients, monkeypatch):
    fake = _install(clients, monkeypatch, [500, 200])

    response = await clients.langflow_request("POST", RUN_ENDPOINT, json={})

    assert response.status_code == 500
    assert len(fake.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [408, 500, 502, 504])
async def test_post_is_not_retried_on_statuses_after_processing(clients, monkeypatch, status):
    fake = _install(clients, monkeypatch, [status, 200])

    response = await clients.langflow_request("POST", RUN_ENDPOINT)

    assert response.status_code == status
    assert len(fake.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_post_is_retried_when_the_server_did_not_process_it(clients, monkeypatch, status):
    fake = _install(clients, monkeypatch, [status, 200])

    response = await clients.langflow_request("POST", RUN_ENDPOINT)

    assert response.status_code == 200
    assert len(fake.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [408, 500, 502, 503, 504])
async def test_get_is_retried_on_transient_statuses(clients, monkeypatch, status):
    fake = _install(clients, monkeypatch, [status, status, 200])

    response = await clients.langflow_request("GET", "/api/v1/flows/x")

    assert response.status_code == 200
    assert len(fake.calls) == 3


@pytest.mark.asyncio
async def test_retries_stop_at_the_configured_budget(clients, monkeypatch):
    fake = _install(clients, monkeypatch, [502, 502, 502, 200])

    response = await clients.langflow_request("GET", "/api/v1/flows/x")

    assert response.status_code == 502
    assert len(fake.calls) == 3


@pytest.mark.asyncio
async def test_patch_is_not_retried_by_default(clients, monkeypatch):
    fake = _install(clients, monkeypatch, [500, 200])

    response = await clients.langflow_request("PATCH", "/api/v1/mcp/project/p")

    assert response.status_code == 500
    assert len(fake.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_an_explicitly_idempotent_request_is_retried(clients, monkeypatch, method):
    fake = _install(clients, monkeypatch, [500, 200])

    response = await clients.langflow_request(method, "/api/v1/flows/x", idempotent=True)

    assert response.status_code == 200
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_an_explicitly_non_idempotent_get_is_not_retried(clients, monkeypatch):
    fake = _install(clients, monkeypatch, [500, 200])

    response = await clients.langflow_request("GET", "/api/v1/flows/x", idempotent=False)

    assert response.status_code == 500
    assert len(fake.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error_cls", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
async def test_post_is_retried_when_it_never_reached_langflow(clients, monkeypatch, error_cls):
    fake = _install(clients, monkeypatch, [_request_error(error_cls), 200])

    response = await clients.langflow_request("POST", RUN_ENDPOINT)

    assert response.status_code == 200
    assert len(fake.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_cls", [httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ReadError]
)
async def test_post_is_not_retried_after_it_may_have_run(clients, monkeypatch, error_cls):
    fake = _install(clients, monkeypatch, [_request_error(error_cls), 200])

    with pytest.raises(error_cls):
        await clients.langflow_request("POST", RUN_ENDPOINT)

    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_get_is_retried_after_a_read_timeout(clients, monkeypatch):
    fake = _install(clients, monkeypatch, [_request_error(httpx.ReadTimeout), 200])

    response = await clients.langflow_request("GET", "/api/v1/flows/x")

    assert response.status_code == 200
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_auth_refresh_still_applies_to_post(clients, monkeypatch):
    fake = _install(clients, monkeypatch, [401, 200])

    response = await clients.langflow_request("POST", RUN_ENDPOINT)

    assert response.status_code == 200
    assert len(fake.calls) == 2


def test_idempotency_follows_rfc_9110_by_default():
    for method in ("GET", "head", "OPTIONS", "PUT", "DELETE"):
        assert settings._is_idempotent_request(method, None) is True
    for method in ("POST", "PATCH", "patch"):
        assert settings._is_idempotent_request(method, None) is False
    assert settings._is_idempotent_request("POST", True) is True
    assert settings._is_idempotent_request("GET", False) is False
