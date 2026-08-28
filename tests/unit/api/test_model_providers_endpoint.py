"""The endpoints that publish which model providers a deployment offers.

The console and any SDK client must be told the same thing, and neither may be
able to read a provider the run mode hides — that is the whole point of moving
the denylist out of the frontend (#2287).
"""

import inspect
import json

import pytest
from fastapi import params as fastapi_params

from api import models as models_api
from api.v1 import llm as v1_llm
from config import model_providers
from session_manager import User


def _user() -> User:
    return User(user_id="u1", email="u@x", name="U", provider="api_key")


def _dependency(fn):
    default = inspect.signature(fn).parameters["user"].default
    assert isinstance(default, fastapi_params.Depends)
    return default.dependency


@pytest.fixture(autouse=True)
def _fresh_provider_config():
    model_providers.reload()
    yield
    model_providers.reload()


def _body(response) -> dict:
    assert response.status_code == 200
    return json.loads(response.body)


def test_console_endpoint_requires_providers_read():
    dep = _dependency(models_api.get_model_providers)
    perms = [cell.cell_contents for cell in dep.__closure__]
    assert "providers:read" in perms


def test_v1_endpoint_requires_a_catalogue_reading_permission():
    dep = _dependency(v1_llm.model_providers_endpoint)
    required = [cell.cell_contents for cell in dep.__closure__]
    assert any("providers:read" in str(item) for item in required)


@pytest.mark.asyncio
async def test_saas_does_not_publish_ollama(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    body = _body(await models_api.get_model_providers(user=_user()))

    assert body["run_mode"] == "saas"
    assert "ollama" not in {entry["name"] for entry in body["providers"]}


@pytest.mark.asyncio
async def test_on_prem_still_publishes_ollama(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "on_prem")
    body = _body(await models_api.get_model_providers(user=_user()))

    assert body["run_mode"] == "on_prem"
    assert "ollama" in {entry["name"] for entry in body["providers"]}


@pytest.mark.asyncio
async def test_the_console_and_v1_endpoints_agree(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    console = _body(await models_api.get_model_providers(user=_user()))
    public = _body(await v1_llm.model_providers_endpoint(user=_user()))

    assert console == public


@pytest.mark.asyncio
async def test_an_override_file_drives_the_payload(monkeypatch, tmp_path):
    path = tmp_path / "model_providers.yaml"
    path.write_text(
        "providers:\n  - name: ollama\n    display_name: Ollama\n    modes:\n      saas: true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(model_providers.CONFIG_PATH_ENV, str(path))
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")

    body = _body(await models_api.get_model_providers(user=_user()))
    assert body["providers"] == [{"name": "ollama", "display_name": "Ollama"}]


@pytest.mark.asyncio
async def test_the_provider_list_is_never_stored_by_the_browser():
    """A cached copy outlives the restart that applies a config edit.

    `config/model_providers.yaml` is read once per process, so changing it means
    editing the file and restarting the backend. With a `max-age` on this
    response the browser answers the next page load from its own cache, the
    console redraws the previous provider cards and tabs, and the edit looks
    like it did nothing — for as long as the max-age lasts.
    """
    for response in (
        await models_api.get_model_providers(user=_user()),
        await v1_llm.model_providers_endpoint(user=_user()),
    ):
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_the_catalogue_is_never_stored_by_the_browser():
    """Same trap as the provider list, and the catalogue is what the pickers read."""
    for response in (
        await models_api.get_model_catalog(user=_user()),
        await v1_llm.model_catalog_endpoint(user=_user()),
    ):
        assert response.headers["cache-control"] == "no-store"
