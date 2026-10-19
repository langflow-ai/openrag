"""`POST /models/{provider}/discover`: what a cluster serves, before it is saved.

Onboarding asks this while the operator is still typing, because the catalogue
lists a cluster only with *saved* credentials and a vLLM `--served-model-name`
can be anything.
"""

import inspect
import json
from types import SimpleNamespace
from typing import Any

import pydantic
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


def _offer_rhoai(
    tmp_path, monkeypatch, *, visible: bool = True, exclude: str = "", vision: str = ""
) -> None:
    config = tmp_path / "model_providers.yaml"
    config.write_text(
        "providers:\n"
        "  - name: rhoai\n"
        "    display_name: Red Hat OpenShift AI\n"
        "    modes:\n"
        f"      oss: {'true' if visible else 'false'}\n"
        "    models:\n      - granite-3.3-2b-instruct\n"
        + (f"    exclude_models:\n      - '{exclude}'\n" if exclude else "")
        + (f"    vision_models:\n      - '{vision}'\n" if vision else "")
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


def _kind_aware_listing(monkeypatch, result: Any) -> list[Any]:
    """A lister that declares `kind`, recording what each call passed (or `"omitted"`)."""
    kinds: list[Any] = []

    async def _list(credentials, *, kind="omitted"):
        kinds.append(kind)
        return result

    monkeypatch.setattr(rhoai, "list_cluster_models", _list)
    return kinds


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "embedding"])
async def test_the_picker_kind_reaches_a_lister_that_takes_it(tmp_path, monkeypatch, kind):
    """Each onboarding step asks for its own picker, so a dead embedding
    endpoint cannot stall the language step."""
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(monkeypatch)
    kinds = _kind_aware_listing(monkeypatch, rhoai.ClusterModels(chat=None, embedding=None))

    response = await models_api.discover_provider_models(
        "rhoai",
        body=models_api.ModelDiscoveryBody(
            credentials={"api_base": CHAT_BASE, "api_key": "t"}, kind=kind
        ),
        user=SimpleNamespace(),
    )

    assert response.status_code == 200
    assert kinds == [kind]


@pytest.mark.asyncio
async def test_without_a_kind_the_lister_is_asked_for_both(tmp_path, monkeypatch):
    """An older client that sends no kind keeps the both-pickers behaviour."""
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(monkeypatch)
    kinds = _kind_aware_listing(monkeypatch, rhoai.ClusterModels(chat=None, embedding=None))

    await _discover(api_base=CHAT_BASE, api_key="t")

    assert kinds == ["omitted"]


@pytest.mark.asyncio
async def test_a_lister_without_a_kind_is_called_without_one(tmp_path, monkeypatch):
    """A single-endpoint provider lists everything at once and takes no kind."""
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(monkeypatch)
    seen = _listing(monkeypatch, rhoai.ClusterModels(chat=("gpt-oss-120b",), embedding=None))

    response = await models_api.discover_provider_models(
        "rhoai",
        body=models_api.ModelDiscoveryBody(
            credentials={"api_base": CHAT_BASE, "api_key": "t"}, kind="embedding"
        ),
        user=SimpleNamespace(),
    )

    assert response.status_code == 200
    assert seen == {"api_base": CHAT_BASE, "api_key": "t"}


def test_an_unknown_kind_is_rejected():
    with pytest.raises(pydantic.ValidationError):
        models_api.ModelDiscoveryBody(kind="rerank")


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
async def test_vision_models_tag_discovered_chat_rows(tmp_path, monkeypatch):
    """`vision_models` reaches discovery too, and never an embedding row."""
    _offer_rhoai(tmp_path, monkeypatch, vision="*-vision-*")
    _saved(monkeypatch)
    _listing(
        monkeypatch,
        rhoai.ClusterModels(
            chat=("granite-vision-3.3-2b", "gpt-oss-120b"),
            embedding=("granite-vision-embedding",),
        ),
    )

    body = json.loads((await _discover(api_base=CHAT_BASE, api_key="t")).body)

    capabilities = {row["model"]: row.get("capabilities") for row in body["models"]}
    assert capabilities == {"granite-vision-3.3-2b": ["vision"], "gpt-oss-120b": None}
    assert "capabilities" not in body["embedding_models"][0]


@pytest.mark.asyncio
async def test_discovered_rows_match_the_catalogue_for_the_same_listing(tmp_path, monkeypatch):
    """One id reads the same before its credentials are saved as after.

    Discovery answers for the unsaved form and the catalogue for the saved
    one; if a config rule reached only one of them, a model would change
    capabilities — or reappear — the moment onboarding was submitted.
    """
    _offer_rhoai(tmp_path, monkeypatch, exclude="internal-*", vision="*-vision-*")
    _saved(monkeypatch)
    listed = rhoai.ClusterModels(
        chat=("gpt-oss-120b", "granite-vision-3.3-2b", "internal-draft"),
        embedding=("granite-embedding-english-r2", "internal-embed"),
    )
    _listing(monkeypatch, listed)
    monkeypatch.setattr(rhoai, "cached_models", lambda: listed)

    body = json.loads((await _discover(api_base=CHAT_BASE, api_key="t")).body)
    catalogued = next(
        entry for entry in model_catalog.catalog()["providers"] if entry["key"] == "rhoai"
    )

    def _by_model(rows):
        return sorted(rows, key=lambda row: row["model"])

    assert _by_model(body["models"]) == _by_model(catalogued["models"])
    assert _by_model(body["embedding_models"]) == _by_model(catalogued["embedding_models"])


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
@pytest.mark.parametrize(
    "cleared, saved_extra",
    [
        ("embedding_api_base", {}),
        ("ssl_verify", {"ssl_verify": "/etc/pki/cluster-ca.crt"}),
    ],
)
async def test_clearing_a_saved_target_is_a_new_target(tmp_path, monkeypatch, cleared, saved_extra):
    # Submit sends a cleared field as a removal, so discovery must not ask the
    # cluster with the stored value — nor send the saved token along with it.
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(
        monkeypatch,
        api_base=CHAT_BASE,
        embedding_api_base=EMBED_BASE,
        api_key=SAVED_TOKEN,
        **saved_extra,
    )
    seen = _listing(monkeypatch, rhoai.ClusterModels(chat=None, embedding=None))

    await _discover(api_base=CHAT_BASE, api_key="", **{cleared: ""})

    assert seen == {"api_base": CHAT_BASE}


@pytest.mark.asyncio
async def test_a_blank_target_that_was_never_saved_keeps_the_saved_token(tmp_path, monkeypatch):
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(monkeypatch, api_base=CHAT_BASE, api_key=SAVED_TOKEN)
    seen = _listing(monkeypatch, rhoai.ClusterModels(chat=None, embedding=None))

    await _discover(api_base=CHAT_BASE, embedding_api_base="", ssl_verify="  ", api_key="")

    assert seen == {"api_base": CHAT_BASE, "api_key": SAVED_TOKEN}


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
    """A bad request, not a server fault: 400 with a fixed message, not the hook's."""
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(monkeypatch)
    _listing(monkeypatch, rhoai.ClusterModels(chat=("x",), embedding=None))

    def _fields(method):
        raise ValueError("hook detail: exposed-secret")

    monkeypatch.setattr(rhoai, "credential_fields_for_auth_method", _fields, raising=False)

    response = await models_api.discover_provider_models(
        "rhoai",
        body=models_api.ModelDiscoveryBody(
            credentials={"api_base": CHAT_BASE, "api_key": "t"}, auth_method="bogus"
        ),
        user=SimpleNamespace(),
    )

    assert response.status_code == 400
    assert json.loads(response.body) == {"error": models_api._INVALID_AUTH_METHOD_ERROR}
    assert b"exposed-secret" not in response.body


@pytest.mark.asyncio
async def test_the_provider_picks_the_auth_method_when_none_is_given(tmp_path, monkeypatch):
    """The fallback is the enhancement's own rule, not one written into the route."""
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(monkeypatch)
    seen = _listing(monkeypatch, rhoai.ClusterModels(chat=None, embedding=None))
    methods: list[str] = []

    def _fields(method):
        methods.append(method)
        return frozenset({"api_base", "api_key"})

    monkeypatch.setattr(rhoai, "credential_fields_for_auth_method", _fields, raising=False)
    monkeypatch.setattr(rhoai, "default_auth_method", lambda stored: "token", raising=False)

    await _discover(api_base=CHAT_BASE, api_key="t", ssl_verify="false")

    assert methods == ["token"]
    assert seen == {"api_base": CHAT_BASE, "api_key": "t"}


@pytest.mark.asyncio
async def test_no_auth_method_and_no_default_is_a_client_error(tmp_path, monkeypatch):
    _offer_rhoai(tmp_path, monkeypatch)
    _saved(monkeypatch)
    _listing(monkeypatch, rhoai.ClusterModels(chat=None, embedding=None))
    monkeypatch.setattr(
        rhoai,
        "credential_fields_for_auth_method",
        lambda method: frozenset({"api_base", "api_key"}),
        raising=False,
    )

    response = await _discover(api_base=CHAT_BASE, api_key="t")

    assert response.status_code == 400
    assert json.loads(response.body) == {"error": models_api._INVALID_AUTH_METHOD_ERROR}


def test_the_catalogue_says_which_providers_can_discover(tmp_path, monkeypatch):
    _offer_rhoai(tmp_path, monkeypatch)

    entries = {entry["key"]: entry for entry in model_catalog.catalog()["providers"]}

    assert entries["rhoai"]["discovers_models"] is True
    assert entries["openai"]["discovers_models"] is False
