"""`POST /models/{provider}/discover`: what a cluster serves, before it is saved.

Onboarding asks this while the operator is still typing, because the catalogue
lists a cluster only with *saved* credentials and a vLLM `--served-model-name`
can be anything.
"""

import inspect
import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import params as fastapi_params

import config.model_providers as model_providers
from api import models as models_api
from config.config_manager import (
    AnthropicConfig,
    GenericProviderConfig,
    OllamaConfig,
    OpenAIConfig,
    ProvidersConfig,
    WatsonXConfig,
)
from enhancements.providers.redhat import openshift_ai as rhoai
from services import model_catalog

CHAT_BASE = "https://chat.example.com/v1"
EMBED_BASE = "https://embed.example.com/v1"
SAVED_TOKEN = "sha256~saved"


@pytest.fixture(autouse=True)
def _fresh_provider_config():
    model_providers.reload()
    yield
    model_providers.reload()


def _offer_rhoai(tmp_path, monkeypatch, *, visible: bool = True, exclude: str = "") -> None:
    config = tmp_path / "model_providers.yaml"
    config.write_text(
        "providers:\n"
        "  - name: rhoai\n"
        "    display_name: Red Hat OpenShift AI\n"
        "    modes:\n"
        f"      oss: {'true' if visible else 'false'}\n"
        "    models:\n      - granite-3.3-2b-instruct\n"
        + (f"    exclude_models:\n      - '{exclude}'\n" if exclude else "")
        + "  - name: openai\n"
        "    display_name: OpenAI\n"
        "    modes:\n"
        "      oss: true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setenv("OPENRAG_MODEL_PROVIDERS_CONFIG", str(config))
    model_providers.reload()


def _saved(monkeypatch, **credentials: Any) -> None:
    providers = ProvidersConfig(
        openai=OpenAIConfig(),
        anthropic=AnthropicConfig(),
        watsonx=WatsonXConfig(),
        ollama=OllamaConfig(),
        custom={"rhoai": GenericProviderConfig(credentials=credentials, configured=True)}
        if credentials
        else {},
    )
    monkeypatch.setattr(
        models_api, "get_openrag_config", lambda: SimpleNamespace(providers=providers)
    )


def _listing(monkeypatch, result: Any) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    async def _list(credentials):
        seen.update(credentials)
        return result

    monkeypatch.setattr(rhoai, "list_cluster_models", _list)
    return seen


async def _discover(provider: str = "rhoai", **credentials: str):
    return await models_api.discover_provider_models(
        provider,
        body=models_api.ModelDiscoveryBody(credentials=credentials),
        user=SimpleNamespace(),
    )


def test_it_requires_providers_write():
    """It sends credentials to an operator-typed host, like the spaces route."""
    default = inspect.signature(models_api.discover_provider_models).parameters["user"].default
    assert isinstance(default, fastapi_params.Depends)
    perms = [cell.cell_contents for cell in default.dependency.__closure__]
    assert "providers:write" in perms


@pytest.mark.asyncio
async def test_the_cluster_listing_reaches_both_pickers(tmp_path, monkeypatch):
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(monkeypatch)
    _listing(
        monkeypatch,
        rhoai.ClusterModels(chat=("gpt-oss-120b",), embedding=("granite-embedding-english-r2",)),
    )

    response = await _discover(api_base=CHAT_BASE, api_key="typed-token")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert json.loads(response.body) == {
        "models": [{"model": "gpt-oss-120b", "mode": "chat"}],
        "embedding_models": [{"model": "granite-embedding-english-r2", "mode": "embedding"}],
    }


@pytest.mark.asyncio
async def test_a_half_that_could_not_be_listed_is_null(tmp_path, monkeypatch):
    """Null tells the picker to keep the catalogue's rows; [] would empty it."""
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(monkeypatch)
    _listing(monkeypatch, rhoai.ClusterModels(chat=("gpt-oss-120b",), embedding=None))

    body = json.loads((await _discover(api_base=CHAT_BASE, api_key="t")).body)

    assert body["embedding_models"] is None


@pytest.mark.asyncio
async def test_excluded_models_stay_excluded(tmp_path, monkeypatch):
    _offer_rhoai(tmp_path, monkeypatch, exclude="internal-*")
    _saved(monkeypatch)
    _listing(
        monkeypatch,
        rhoai.ClusterModels(chat=("gpt-oss-120b", "internal-draft"), embedding=None),
    )

    body = json.loads((await _discover(api_base=CHAT_BASE, api_key="t")).body)

    assert [row["model"] for row in body["models"]] == ["gpt-oss-120b"]


@pytest.mark.asyncio
async def test_a_saved_token_fills_a_blank_secret_on_the_same_host(tmp_path, monkeypatch):
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(monkeypatch, api_base=CHAT_BASE, embedding_api_base=EMBED_BASE, api_key=SAVED_TOKEN)
    seen = _listing(monkeypatch, rhoai.ClusterModels(chat=None, embedding=None))

    await _discover(api_base=CHAT_BASE, api_key="")

    assert seen == {
        "api_base": CHAT_BASE,
        "embedding_api_base": EMBED_BASE,
        "api_key": SAVED_TOKEN,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [
        {"api_base": "https://elsewhere.example.com/v1"},
        {"embedding_api_base": "https://elsewhere.example.com/v1"},
        {"ssl_verify": "false"},
    ],
)
async def test_a_saved_token_never_goes_to_a_new_target(tmp_path, monkeypatch, changed):
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(monkeypatch, api_base=CHAT_BASE, embedding_api_base=EMBED_BASE, api_key=SAVED_TOKEN)
    seen = _listing(monkeypatch, rhoai.ClusterModels(chat=None, embedding=None))

    await _discover(**changed)

    assert seen == changed


@pytest.mark.asyncio
async def test_fields_the_form_does_not_define_are_dropped(tmp_path, monkeypatch):
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(monkeypatch)
    seen = _listing(monkeypatch, rhoai.ClusterModels(chat=None, embedding=None))

    await _discover(api_base=CHAT_BASE, api_key="t", extra_headers="x")

    assert "extra_headers" not in seen


@pytest.mark.asyncio
async def test_a_provider_that_cannot_list_its_models_is_404(tmp_path, monkeypatch):
    _offer_rhoai(tmp_path, monkeypatch)

    assert (await _discover("openai")).status_code == 404
    assert (await _discover("no-such-provider")).status_code == 404


@pytest.mark.asyncio
async def test_a_hidden_provider_is_404(tmp_path, monkeypatch):
    _offer_rhoai(tmp_path, monkeypatch, visible=False)
    _listing(monkeypatch, rhoai.ClusterModels(chat=("x",), embedding=None))

    assert (await _discover(api_base=CHAT_BASE, api_key="t")).status_code == 404


@pytest.mark.asyncio
async def test_an_unexpected_failure_is_not_echoed(tmp_path, monkeypatch):
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(monkeypatch)

    async def _boom(credentials):
        raise RuntimeError("Traceback: Bearer exposed-secret")

    monkeypatch.setattr(rhoai, "list_cluster_models", _boom)

    response = await _discover(api_base=CHAT_BASE, api_key="t")

    assert response.status_code == 500
    assert b"exposed-secret" not in response.body


@pytest.mark.asyncio
async def test_an_unknown_auth_method_is_a_client_error(tmp_path, monkeypatch):
    """A bad request, not a server fault: 400 with the provider's message."""
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(monkeypatch)
    _listing(monkeypatch, rhoai.ClusterModels(chat=("x",), embedding=None))

    def _fields(method):
        raise ValueError("Choose a valid authentication method")

    monkeypatch.setattr(rhoai, "credential_fields_for_auth_method", _fields, raising=False)

    response = await models_api.discover_provider_models(
        "rhoai",
        body=models_api.ModelDiscoveryBody(
            credentials={"api_base": CHAT_BASE, "api_key": "t"}, auth_method="bogus"
        ),
        user=SimpleNamespace(),
    )

    assert response.status_code == 400
    assert json.loads(response.body) == {"error": "Choose a valid authentication method"}


def test_the_catalogue_says_which_providers_can_discover(tmp_path, monkeypatch):
    _offer_rhoai(tmp_path, monkeypatch)

    entries = {entry["key"]: entry for entry in model_catalog.catalog()["providers"]}

    assert entries["rhoai"]["discovers_models"] is True
    assert entries["openai"]["discovers_models"] is False
