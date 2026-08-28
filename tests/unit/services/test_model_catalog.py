"""The LiteLLM-derived model catalogue.

The catalogue replaced per-provider live `/models/{provider}` fetches for the
settings dropdown, so these tests pin the properties that table used to
guarantee: a picked model names a provider LiteLLM can call, chat and embedding
lists are disjoint, and the OpenAI-compatible /v1/models list is derived from
the same payload.
"""

from __future__ import annotations

import pytest

from config import model_providers
from services import model_catalog


@pytest.fixture(autouse=True)
def _fresh_provider_config():
    """Run-mode tests below rewrite the provider config; don't leak the cache."""
    model_providers.reload()
    yield
    model_providers.reload()


def test_catalog_only_groups_supported_providers_with_their_models_and_forms() -> None:
    providers = {entry["key"]: entry for entry in model_catalog.catalog()["providers"]}

    assert set(providers) == model_catalog.supported_provider_keys()
    for key in model_catalog.supported_provider_keys():
        assert key in providers, key
        assert providers[key]["credential_fields"], key

    openai = providers["openai"]
    assert openai["name"] == "OpenAI"
    assert any(entry["model"].startswith("gpt-") for entry in openai["models"])
    assert any("embedding" in entry["model"] for entry in openai["embedding_models"])
    field_types = {field["key"]: field["field_type"] for field in openai["credential_fields"]}
    assert field_types["api_key"] == "password"
    assert field_types["api_base"] == "text"


def test_catalog_chat_models_are_only_text_generation() -> None:
    modes = {
        entry["mode"]
        for provider in model_catalog.catalog()["providers"]
        for entry in provider["models"]
    }
    assert modes <= model_catalog.TEXT_GENERATION_MODES
    assert "chat" in modes


def test_catalog_embedding_models_are_only_embedding_mode() -> None:
    modes = {
        entry["mode"]
        for provider in model_catalog.catalog()["providers"]
        for entry in provider["embedding_models"]
    }
    assert modes <= {model_catalog.EMBEDDING_MODE}
    assert model_catalog.EMBEDDING_MODE in modes


def test_model_ids_are_stored_without_their_provider_prefix() -> None:
    providers = {entry["key"]: entry for entry in model_catalog.catalog()["providers"]}
    for provider, entry in providers.items():
        for model in entry["models"] + entry["embedding_models"]:
            assert not model["model"].startswith(f"{provider}/")


def test_openai_form_is_the_plain_one_not_the_compatible_variant() -> None:
    required = model_catalog.required_field_keys("openai")
    assert required == ["api_key"]


def test_an_unknown_provider_still_gets_a_usable_form() -> None:
    fields = model_catalog.credential_fields("some-private-gateway")
    assert [field["key"] for field in fields] == ["api_key", "api_base"]
    assert model_catalog.missing_required_fields("some-private-gateway", set()) == []


def test_openai_models_list_is_openai_compatible() -> None:
    payload = model_catalog.openai_models_list()
    assert payload["object"] == "list"
    assert payload["data"]
    ids = {row["id"] for row in payload["data"]}
    assert any(model_id.startswith("gpt-") for model_id in ids)
    sample = payload["data"][0]
    assert sample["object"] == "model"
    assert "owned_by" in sample


def test_is_known_provider_accepts_litellm_handlers() -> None:
    assert model_catalog.is_known_provider("openai")
    assert model_catalog.is_known_provider("anthropic")
    assert not model_catalog.is_known_provider("not-a-real-provider")
    assert not model_catalog.is_known_provider("")


def test_is_known_provider_covers_every_provider_litellm_can_route() -> None:
    """`provider_list` is enum members, not strings.

    Reading them with str() gives "LlmProviders.OPENAI", so the check silently
    fell through to the credential-form specs — which omit ~26 routable
    providers. Their `provider/model` ids were then left unsplit and billed to
    whatever the default provider was.
    """
    import litellm

    routable = {getattr(value, "value", str(value)) for value in litellm.provider_list}
    assert routable, "litellm exposes no provider list"
    missing = sorted(key for key in routable if not model_catalog.is_known_provider(key))
    assert not missing, missing


def test_a_routable_prefix_without_a_credential_form_still_splits() -> None:
    from services.llm_gateway import split_model_id

    assert split_model_id("zai/glm-4.6") == ("zai", "glm-4.6")
    assert split_model_id("not-a-provider/x") == (None, "not-a-provider/x")


def test_exported_model_ids_route_back_to_their_owner() -> None:
    """A `/v1/models` id must resolve to the provider that owns it.

    `_catalog()` strips provider prefixes for the picker; without re-attaching
    them here an Anthropic id sent to `/v1/chat/completions` would fall through
    to the default provider and be called with the wrong credentials.
    """
    from services.llm_gateway import split_model_id

    payload = model_catalog.openai_models_list()
    non_openai = [row for row in payload["data"] if row["owned_by"] != "openai"]
    assert non_openai, "catalogue should expose more than OpenAI"

    for row in non_openai:
        provider, _name = split_model_id(row["id"])
        assert provider == row["owned_by"], row

    openai_rows = [row for row in payload["data"] if row["owned_by"] == "openai"]
    assert openai_rows
    assert all("/" not in row["id"] for row in openai_rows)


def test_catalog_hides_a_provider_the_run_mode_does_not_expose(monkeypatch) -> None:
    """SaaS must not advertise Ollama; oss and on-prem must keep it."""
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    saas = {entry["key"] for entry in model_catalog.catalog()["providers"]}
    assert "ollama" not in saas
    assert "openai" in saas

    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    assert "ollama" in {entry["key"] for entry in model_catalog.catalog()["providers"]}


def test_catalog_publishes_azure_ai_where_the_config_enables_it(monkeypatch) -> None:
    for mode in ("oss", "on_prem", "saas"):
        monkeypatch.setenv("OPENRAG_RUN_MODE", mode)
        providers = {entry["key"]: entry for entry in model_catalog.catalog()["providers"]}
        assert "azure_ai" in providers, mode
        azure = providers["azure_ai"]
        assert azure["name"] == "Azure AI Foundry"
        assert azure["models"], mode
        assert azure["embedding_models"], mode
        assert {"api_base", "api_key"} <= {field["key"] for field in azure["credential_fields"]}


def test_azure_openai_is_the_row_that_carries_the_gpt_41_family(monkeypatch) -> None:
    """The two Azure rows are not interchangeable.

    LiteLLM files Azure OpenAI Service under `azure` and the Foundry catalogue
    under `azure_ai`, and only the former lists gpt-4.1. Offering just
    `azure_ai` — as the config first did — leaves no way to pick gpt-4.1 from
    the dropdown at all.
    """
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    providers = {entry["key"]: entry for entry in model_catalog.catalog()["providers"]}

    assert providers["azure"]["name"] == "Azure OpenAI"
    assert "gpt-4.1" in {entry["model"] for entry in providers["azure"]["models"]}
    assert "gpt-4.1" not in {entry["model"] for entry in providers["azure_ai"]["models"]}
    # The prefix is stripped for display but re-attached on the way out, or the
    # id would be called with the default provider's credentials.
    assert "azure:gpt-4.1" in {row["id"] for row in model_catalog.openai_models_list()["data"]}


def test_openai_models_list_drops_a_hidden_providers_models(monkeypatch) -> None:
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    owners = {row["owned_by"] for row in model_catalog.openai_models_list()["data"]}
    assert "ollama" not in owners

    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    assert "ollama" in {row["owned_by"] for row in model_catalog.openai_models_list()["data"]}


def test_the_config_display_name_names_the_provider(monkeypatch, tmp_path) -> None:
    """A catalogue entry is labelled by the config file, not by LiteLLM."""
    path = tmp_path / "model_providers.yaml"
    path.write_text(
        "providers:\n  - name: openai\n    display_name: House Gateway\n"
        "    modes:\n      oss: true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(model_providers.CONFIG_PATH_ENV, str(path))
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")

    providers = model_catalog.catalog()["providers"]
    assert [entry["key"] for entry in providers] == ["openai"]
    assert providers[0]["name"] == "House Gateway"


def _write_providers(tmp_path, body: str) -> str:
    path = tmp_path / "model_providers.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_a_custom_gateway_can_declare_the_models_it_serves(monkeypatch, tmp_path) -> None:
    """LiteLLM's table has no ids for a self-hosted OpenAI-compatible endpoint.

    Without config-declared ids the provider would render a card and a working
    credential form, then offer an empty model picker.
    """
    monkeypatch.setenv(
        model_providers.CONFIG_PATH_ENV,
        _write_providers(
            tmp_path,
            """
providers:
  - name: openai_like
    display_name: Internal LLM Gateway
    modes:
      oss: true
    models:
      - llama-3.3-70b-instruct
    embedding_models:
      - bge-m3
""",
        ),
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")

    providers = model_catalog.catalog()["providers"]
    assert [entry["key"] for entry in providers] == ["openai_like"]
    gateway = providers[0]
    assert gateway["name"] == "Internal LLM Gateway"
    assert [entry["model"] for entry in gateway["models"]] == ["llama-3.3-70b-instruct"]
    assert [entry["model"] for entry in gateway["embedding_models"]] == ["bge-m3"]
    # The endpoint has to be enterable, or the gateway is unreachable.
    assert "api_base" in {field["key"] for field in gateway["credential_fields"]}


def test_a_declared_gateway_model_routes_back_to_its_own_provider(monkeypatch, tmp_path) -> None:
    from services.llm_gateway import PROVIDER_SEPARATOR, split_model_id

    monkeypatch.setenv(
        model_providers.CONFIG_PATH_ENV,
        _write_providers(
            tmp_path,
            "providers:\n  - name: openai_like\n    modes:\n      oss: true\n"
            "    models:\n      - llama-3.3-70b-instruct\n",
        ),
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")

    ids = [row["id"] for row in model_catalog.openai_models_list()["data"]]
    assert ids == [f"openai_like{PROVIDER_SEPARATOR}llama-3.3-70b-instruct"]
    assert split_model_id(ids[0]) == ("openai_like", "llama-3.3-70b-instruct")


def test_declared_ids_do_not_duplicate_what_litellm_already_lists(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        model_providers.CONFIG_PATH_ENV,
        _write_providers(
            tmp_path,
            "providers:\n  - name: openai\n    modes:\n      oss: true\n"
            "    models:\n      - gpt-4o\n      - house-tuned-gpt\n",
        ),
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")

    models = [entry["model"] for entry in model_catalog.catalog()["providers"][0]["models"]]
    assert models.count("gpt-4o") == 1
    assert "house-tuned-gpt" in models
