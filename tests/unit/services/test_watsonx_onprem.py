"""watsonx.ai on a Cloud Pak for Data cluster, routed through LiteLLM's watsonx provider."""

from types import SimpleNamespace

import pytest

from config import model_providers
from config.config_manager import (
    AnthropicConfig,
    GenericProviderConfig,
    OllamaConfig,
    OpenAIConfig,
    ProvidersConfig,
    WatsonXConfig,
)
from services import model_catalog, watsonx_onprem
from services.llm_gateway import resolve_call

PROVIDER = watsonx_onprem.PROVIDER_KEY


@pytest.fixture(autouse=True)
def _reload_provider_config():
    model_providers.reload()
    yield
    model_providers.reload()


def _providers(**credentials) -> ProvidersConfig:
    return ProvidersConfig(
        openai=OpenAIConfig(),
        anthropic=AnthropicConfig(),
        watsonx=WatsonXConfig(),
        ollama=OllamaConfig(),
        custom={PROVIDER: GenericProviderConfig(credentials=dict(credentials), configured=True)},
    )


def test_zen_api_key_is_the_base64_cpd_docs_describe() -> None:
    # `echo "<username>:<apikey>" | base64`, which is what the cluster expects
    # after `Authorization: ZenApiKey `.
    assert watsonx_onprem.zen_api_key("cpduser", "APIKEY") == "Y3BkdXNlcjpBUElLRVk="


@pytest.mark.parametrize("username, api_key", [("", "APIKEY"), ("cpduser", ""), (None, None)])
def test_a_half_filled_form_yields_no_zen_key(username, api_key) -> None:
    """Better no credential than one that looks valid and 401s on first use."""
    assert watsonx_onprem.zen_api_key(username, api_key) == ""


def test_username_never_reaches_litellm() -> None:
    """LiteLLM forwards kwargs it does not recognise, so a stray field lands in the body."""
    credentials = watsonx_onprem.litellm_credentials(
        {"api_base": "https://cpd.example.com", "username": "cpduser", "api_key": "APIKEY"}
    )

    assert "username" not in credentials
    assert credentials["api_base"] == "https://cpd.example.com"
    # Both, and the same value: the embeddings path refuses the call outright
    # when api_key is unset, and builds its auth header from zen_api_key.
    assert credentials["zen_api_key"] == "Y3BkdXNlcjpBUElLRVk="
    assert credentials["api_key"] == "Y3BkdXNlcjpBUElLRVk="


def test_a_pasted_zen_key_is_used_as_given() -> None:
    credentials = watsonx_onprem.litellm_credentials(
        {"api_base": "https://cpd.example.com", "zen_api_key": "cHJlOmVuY29kZWQ="}
    )

    assert credentials["zen_api_key"] == "cHJlOmVuY29kZWQ="
    assert credentials["api_key"] == "cHJlOmVuY29kZWQ="


def test_an_api_key_with_no_username_is_still_offered_to_litellm() -> None:
    """A cluster fronted by IBM Cloud IAM has no username half. Don't drop the secret."""
    credentials = watsonx_onprem.litellm_credentials(
        {"api_base": "https://cpd.example.com", "api_key": "APIKEY"}
    )

    assert credentials["api_key"] == "APIKEY"
    assert "zen_api_key" not in credentials


def test_a_deployment_scope_is_passed_through_untouched() -> None:
    credentials = watsonx_onprem.litellm_credentials(
        {
            "api_base": "https://cpd.example.com",
            "username": "cpduser",
            "api_key": "APIKEY",
            "space_id": "space-1",
            "project_id": "proj-1",
        }
    )

    assert credentials["space_id"] == "space-1"
    assert credentials["project_id"] == "proj-1"


def test_credential_values_translates_the_stored_form() -> None:
    providers = _providers(api_base="https://cpd.example.com", username="cpduser", api_key="APIKEY")

    assert providers.credential_values(PROVIDER) == {
        "api_base": "https://cpd.example.com",
        "zen_api_key": "Y3BkdXNlcjpBUElLRVk=",
        "api_key": "Y3BkdXNlcjpBUElLRVk=",
    }


def test_pending_credentials_rebuilds_the_zen_key_from_a_submitted_change() -> None:
    """Validation runs before the write, on the union of stored and submitted.

    Merging after the translation would validate a new API key against a Zen
    key still built from the old one.
    """
    providers = _providers(api_base="https://cpd.example.com", username="cpduser", api_key="OLDKEY")

    pending = providers.pending_credentials(PROVIDER, {"api_key": "NEWKEY"})

    assert pending["zen_api_key"] == watsonx_onprem.zen_api_key("cpduser", "NEWKEY")
    assert pending["api_base"] == "https://cpd.example.com"


def test_the_gateway_routes_it_as_watsonx() -> None:
    """`watsonx_onprem/<model>` is not a prefix LiteLLM can resolve."""
    config = SimpleNamespace(
        providers=_providers(
            api_base="https://cpd.example.com", username="cpduser", api_key="APIKEY"
        ),
        agent=SimpleNamespace(llm_model="", llm_provider="openai"),
        knowledge=SimpleNamespace(embedding_model="", embedding_provider="openai"),
    )

    litellm_model, provider, credentials = resolve_call(
        f"{PROVIDER}:ibm/granite-3-3-8b-instruct", kind="chat", config=config
    )

    assert litellm_model == "watsonx/ibm/granite-3-3-8b-instruct"
    # The OpenRAG key is what the caller and the credential store still see.
    assert provider == PROVIDER
    assert credentials["zen_api_key"] == "Y3BkdXNlcjpBUElLRVk="


def test_the_alias_is_routable_so_ids_are_not_billed_to_the_default_provider() -> None:
    assert model_catalog.is_known_provider(PROVIDER)
    assert model_catalog.litellm_provider_key(PROVIDER) == "watsonx"
    assert model_catalog.litellm_provider_key("openai") == "openai"


def test_it_ships_on_prem_only(monkeypatch) -> None:
    monkeypatch.setenv("OPENRAG_RUN_MODE", "on_prem")
    assert PROVIDER in model_providers.visible_provider_keys()

    for mode in ("oss", "saas"):
        monkeypatch.setenv("OPENRAG_RUN_MODE", mode)
        assert PROVIDER not in model_providers.visible_provider_keys(), mode


def test_the_settings_form_asks_for_cluster_credentials_not_ibm_cloud_ones() -> None:
    fields = {field["key"]: field for field in model_catalog.credential_fields(PROVIDER)}

    assert fields["api_base"]["required"] is True
    assert set(fields) == {
        "api_base",
        "username",
        "api_key",
        "zen_api_key",
        "space_id",
        "project_id",
    }
    assert model_catalog.secret_field_keys(PROVIDER) == {"api_key", "zen_api_key"}


def test_its_models_come_from_config_not_ibm_clouds_price_table(monkeypatch) -> None:
    """Two providers sharing model ids would leave `catalog_owner` unable to pick one."""
    monkeypatch.setenv("OPENRAG_RUN_MODE", "on_prem")
    entries = {entry["key"]: entry for entry in model_catalog.catalog()["providers"]}

    onprem = entries[PROVIDER]
    declared = {entry.name: entry for entry in model_providers.visible_provider_entries()}[PROVIDER]

    assert {entry["model"] for entry in onprem["models"]} == set(declared.models)
    assert {entry["model"] for entry in onprem["embedding_models"]} == set(
        declared.embedding_models
    )
    assert onprem["embedding_models"], "an embedding provider with no ids can never be selected"

    shared = {entry["model"] for entry in entries["watsonx"]["models"]} & {
        entry["model"] for entry in onprem["models"]
    }
    for model in shared:
        assert model_catalog.catalog_owner(model) is None or model_catalog.catalog_owner(model) in {
            "watsonx",
            PROVIDER,
        }


def test_a_scopeless_cluster_call_carries_no_null_space_id() -> None:
    """The lightweight engine uses neither a project nor a space.

    LiteLLM 1.84 refuses the call locally and, past that, serialises the absent
    space as `"space_id": null`. Both are wrong for that install.
    """
    watsonx_onprem.install_litellm_compatibility()

    from litellm.llms.watsonx.chat.handler import _get_api_params
    from litellm.llms.watsonx.chat.transformation import IBMWatsonXChatConfig

    api_params = _get_api_params(params={}, model="ibm/granite-3-3-8b-instruct")
    payload = IBMWatsonXChatConfig()._prepare_payload(
        model="ibm/granite-3-3-8b-instruct", api_params=api_params
    )

    assert payload == {"model_id": "ibm/granite-3-3-8b-instruct"}


def test_a_scope_that_is_set_still_reaches_the_cluster() -> None:
    watsonx_onprem.install_litellm_compatibility()

    from litellm.llms.watsonx.chat.handler import _get_api_params
    from litellm.llms.watsonx.chat.transformation import IBMWatsonXChatConfig

    api_params = _get_api_params(
        params={"space_id": "space-1"}, model="ibm/granite-3-3-8b-instruct"
    )
    payload = IBMWatsonXChatConfig()._prepare_payload(
        model="ibm/granite-3-3-8b-instruct", api_params=api_params
    )

    assert payload == {"model_id": "ibm/granite-3-3-8b-instruct", "space_id": "space-1"}
