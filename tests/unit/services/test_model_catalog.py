"""The LiteLLM-derived model catalogue.

The catalogue replaced per-provider live `/models/{provider}` fetches for the
settings dropdown, so these tests pin the properties that table used to
guarantee: a picked model names a provider LiteLLM can call, chat and embedding
lists are disjoint, and the OpenAI-compatible /v1/models list is derived from
the same payload.
"""

from __future__ import annotations

from services import model_catalog


def test_catalog_groups_every_provider_with_its_models_and_form() -> None:
    providers = {entry["key"]: entry for entry in model_catalog.catalog()["providers"]}

    for key in ("openai", "anthropic", "ollama", "watsonx"):
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
    gemini = providers.get("gemini") or providers.get("gemini_openai")
    if gemini is None:
        return
    for entry in gemini["models"]:
        assert not entry["model"].startswith("gemini/")


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
