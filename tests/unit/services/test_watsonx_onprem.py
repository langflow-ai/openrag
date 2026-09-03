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
from services.llm_gateway import resolve_call, split_model_id

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


def test_it_ships_on_prem_and_never_in_saas(monkeypatch) -> None:
    """on_prem is the mode it exists for; SaaS is the one it must never reach.

    Nothing is asserted about `oss`: that row gets flipped on for local testing
    the way `azure_ai`'s is, and a test that pins it only breaks the next person
    who needs the card in their dev stack.
    """
    monkeypatch.setenv("OPENRAG_RUN_MODE", "on_prem")
    assert PROVIDER in model_providers.visible_provider_keys()

    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    assert PROVIDER not in model_providers.visible_provider_keys()


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


def test_an_id_both_watsonx_rows_serve_is_never_handed_to_its_prefix(monkeypatch) -> None:
    """`openai/gpt-oss-120b` is watsonx's model, not OpenAI's.

    A cluster that also serves it puts the id under two providers, so
    `catalog_owner` cannot pick one. The old fallback split on the slash and
    routed it to OpenAI — with OpenAI's key, for a model OpenAI does not have.
    """
    monkeypatch.setenv("OPENRAG_RUN_MODE", "on_prem")
    model = "openai/gpt-oss-120b"

    if len(model_catalog.catalog_owners(model)) < 2:
        pytest.skip("this deployment's config does not list the id under both watsonx rows")

    assert model_catalog.catalog_owner(model) is None
    # Untagged, so it goes to the configured default provider whole rather than
    # to whichever provider the prefix happens to name.
    assert split_model_id(model) == (None, model)


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


def test_a_self_signed_cluster_cert_is_reported_as_a_trust_problem() -> None:
    """The request never leaves the process, so there is no provider error to quote.

    Without this the message collapses to "could not be reached", which sends an
    operator hunting for a network fault instead of a missing CA.
    """
    from services.llm_gateway import _upstream_client_message

    detail = (
        "InternalServerError: WatsonxException - Cannot connect to host "
        "cpd.example.com:443 ssl:True [SSLCertVerificationError: (1, '[SSL: "
        "CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed "
        "certificate in certificate chain (_ssl.c:1032)')]"
    )

    message = _upstream_client_message(detail, PROVIDER, "watsonx/ibm/granite-3-3-8b-instruct")

    assert "TLS certificate is not trusted" in message
    assert "CA certificate" in message
    # Not mistaken for a bad key: rotating a working ZenApiKey fixes nothing.
    assert "API key" not in message


def test_a_revoked_key_still_reads_as_a_credential_problem() -> None:
    from services.llm_gateway import _upstream_client_message

    message = _upstream_client_message(
        'InternalServerError: {"errorCode":"BXNIM0415E","errorMessage":"Provided API key '
        'could not be found."}',
        PROVIDER,
        "watsonx/ibm/granite-3-3-8b-instruct",
    )

    assert "API key is invalid" in message


def test_a_shared_id_reaches_the_cluster_under_the_selected_provider(monkeypatch) -> None:
    """The real failure: `openai/gpt-oss-120b` picked while watsonx_onprem is selected.

    Settings stores the provider and the bare model id separately, so the id
    arrives untagged. Splitting it on the slash threw away the selected provider
    and called OpenAI with OpenAI's key for a model OpenAI does not serve.
    """
    monkeypatch.setenv("OPENRAG_RUN_MODE", "on_prem")
    model = "openai/gpt-oss-120b"
    if len(model_catalog.catalog_owners(model)) < 2:
        pytest.skip("this deployment's config does not list the id under both watsonx rows")

    config = SimpleNamespace(
        providers=_providers(
            api_base="https://cpd.example.com", username="cpduser", api_key="APIKEY"
        ),
        agent=SimpleNamespace(llm_model=model, llm_provider=PROVIDER),
        knowledge=SimpleNamespace(embedding_model="", embedding_provider="openai"),
    )

    litellm_model, provider, credentials = resolve_call(None, kind="chat", config=config)

    assert provider == PROVIDER
    assert litellm_model == f"watsonx/{model}"
    assert credentials["zen_api_key"] == "Y3BkdXNlcjpBUElLRVk="


@pytest.mark.asyncio
async def test_health_needs_no_model_selected(monkeypatch) -> None:
    """The banner reported "A model is required to validate the provider".

    Every generic provider is validated by making a real call, so one that is
    configured but has no model chosen yet failed validation and surfaced as a
    provider error — pointing at the credentials dialog for something that was
    never a credentials problem. The cluster's catalogue endpoint needs no
    model, no project and no space.
    """
    from api import provider_validation

    called: dict[str, object] = {}

    async def _fake_request(method, url, **kwargs):
        called["method"] = method
        called["url"] = url
        called["auth"] = kwargs.get("headers", {}).get("Authorization")
        return SimpleNamespace(status_code=200, text="{}", json=lambda: {"resources": []})

    monkeypatch.setattr(provider_validation, "_http_request_with_retry", _fake_request)

    credentials = watsonx_onprem.litellm_credentials(
        {"api_base": "https://cpd.example.com/", "username": "cpduser", "api_key": "APIKEY"}
    )
    await provider_validation.validate_provider_setup(
        provider=PROVIDER, credentials=credentials, llm_model=None, embedding_model=None
    )

    assert called["method"] == "GET"
    assert called["url"] == (
        "https://cpd.example.com/ml/v1/foundation_model_specs?version=2024-03-13"
    )
    assert called["auth"] == "ZenApiKey Y3BkdXNlcjpBUElLRVk="


@pytest.mark.asyncio
async def test_health_reports_a_rejected_zen_key_as_a_credential_problem(monkeypatch) -> None:
    from api import provider_validation
    from api.provider_validation import is_provider_credential_error

    async def _fake_request(method, url, **kwargs):
        return SimpleNamespace(
            status_code=401,
            text='{"errors":[{"message":"Failed to authenticate the request"}]}',
            json=lambda: {"errors": [{"message": "Failed to authenticate the request"}]},
        )

    monkeypatch.setattr(provider_validation, "_http_request_with_retry", _fake_request)

    credentials = watsonx_onprem.litellm_credentials(
        {"api_base": "https://cpd.example.com", "username": "cpduser", "api_key": "APIKEY"}
    )
    with pytest.raises(Exception) as excinfo:
        await provider_validation.validate_provider_setup(
            provider=PROVIDER, credentials=credentials, llm_model=None, embedding_model=None
        )

    # Classified as a credential failure so the banner offers "update the key"
    # rather than "the provider could not be reached".
    assert is_provider_credential_error(str(excinfo.value))


def test_the_health_probe_uses_the_same_tls_setting_as_real_traffic(monkeypatch) -> None:
    """`SSL_CERT_FILE`/`SSL_VERIFY` are read by LiteLLM, not by httpx.

    Without this the banner could sit red on a certificate error while chat
    through the gateway works, or the reverse.
    """
    from api.provider_validation import _cluster_ssl_verify

    monkeypatch.setenv("SSL_VERIFY", "false")
    assert _cluster_ssl_verify() is False

    monkeypatch.setenv("SSL_VERIFY", "true")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    assert _cluster_ssl_verify() is True
