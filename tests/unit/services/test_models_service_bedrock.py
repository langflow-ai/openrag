"""Unit tests for AWS Bedrock support in ModelsService.

The #1 correctness risk called out in the source issue: search_service's
query-time embed call uses `get_litellm_model_name(model, strict=True)`,
which RAISES if no configured provider claims the model. These tests prove
`update_model_registry()` actually registers Bedrock's models when
configured, and that resolution then produces the exact litellm model
string ("bedrock/cohere.embed-multilingual-v3") search_service needs.
"""

from types import SimpleNamespace

import pytest

from services.models_service import (
    KNOWN_PREFIXES,
    ModelsService,
    UnknownEmbeddingProvider,
    is_cohere_embedding_model,
)


def _config(*, bedrock_region: str = "") -> SimpleNamespace:
    """Minimal config stand-in covering every provider update_model_registry
    touches, so the openai/anthropic/ollama/watsonx branches no-op cleanly."""
    return SimpleNamespace(
        providers=SimpleNamespace(
            openai=SimpleNamespace(api_key=""),
            anthropic=SimpleNamespace(api_key=""),
            ollama=SimpleNamespace(endpoint=""),
            watsonx=SimpleNamespace(api_key="", endpoint="", project_id=""),
            bedrock=SimpleNamespace(region=bedrock_region),
        )
    )


@pytest.fixture(autouse=True)
def _reset_registry():
    """The provider registry is class-level (shared) state - isolate tests."""
    original = ModelsService._model_provider_registry
    ModelsService._model_provider_registry = {}
    yield
    ModelsService._model_provider_registry = original


class TestKnownPrefixes:
    def test_bedrock_is_a_known_prefix(self):
        assert "bedrock" in KNOWN_PREFIXES


class TestIsCohereEmbeddingModel:
    @pytest.mark.parametrize(
        "model_name",
        [
            "cohere.embed-multilingual-v3",
            "cohere.embed-english-v3",
            "cohere.embed-v4:0",
            "bedrock/cohere.embed-multilingual-v3",
            "COHERE.EMBED-MULTILINGUAL-V3",
        ],
    )
    def test_matches_cohere_models(self, model_name):
        assert is_cohere_embedding_model(model_name) is True

    @pytest.mark.parametrize(
        "model_name",
        [
            "text-embedding-3-small",
            "ibm/slate-125m-english-rtrvr",
            "nomic-embed-text",
            "",
            None,
        ],
    )
    def test_does_not_match_non_cohere_models(self, model_name):
        assert is_cohere_embedding_model(model_name) is False


class TestGetBedrockModels:
    @pytest.mark.asyncio
    async def test_returns_static_list_shape(self):
        service = ModelsService()
        result = await service.get_bedrock_models(update_index=False)

        assert result["language_models"] == []
        assert isinstance(result["embedding_models"], list)
        assert len(result["embedding_models"]) >= 1
        for model in result["embedding_models"]:
            assert set(model.keys()) == {"value", "label", "default"}
            assert isinstance(model["value"], str) and model["value"]
            assert isinstance(model["label"], str) and model["label"]
            assert isinstance(model["default"], bool)

    @pytest.mark.asyncio
    async def test_includes_target_multilingual_model_as_default(self):
        service = ModelsService()
        result = await service.get_bedrock_models(update_index=False)

        values = {m["value"]: m for m in result["embedding_models"]}
        assert "cohere.embed-multilingual-v3" in values
        assert values["cohere.embed-multilingual-v3"]["default"] is True
        # Exactly one default.
        assert sum(1 for m in result["embedding_models"] if m["default"]) == 1

    @pytest.mark.asyncio
    async def test_does_not_make_network_calls(self, monkeypatch):
        """Static list: httpx must never be touched."""

        class ExplodingClient:
            def __init__(self, *a, **k):
                raise AssertionError("get_bedrock_models must not make HTTP calls")

        monkeypatch.setattr("httpx.AsyncClient", ExplodingClient)
        service = ModelsService()
        await service.get_bedrock_models(update_index=False)

    @pytest.mark.asyncio
    async def test_update_index_true_registers_models(self):
        service = ModelsService()
        await service.get_bedrock_models(update_index=True)

        assert ModelsService._model_provider_registry.get("cohere.embed-multilingual-v3") == (
            "bedrock"
        )

    @pytest.mark.asyncio
    async def test_update_index_false_does_not_register(self):
        service = ModelsService()
        await service.get_bedrock_models(update_index=False)

        assert "cohere.embed-multilingual-v3" not in ModelsService._model_provider_registry


class TestUpdateModelRegistryBedrockBranch:
    @pytest.mark.asyncio
    async def test_registers_bedrock_models_when_region_configured(self, monkeypatch):
        monkeypatch.setattr(
            "config.config_manager.config_manager",
            SimpleNamespace(get_config=lambda: _config(bedrock_region="eu-central-1")),
        )

        service = ModelsService()
        await service.update_model_registry()

        assert (
            ModelsService._model_provider_registry.get("cohere.embed-multilingual-v3") == "bedrock"
        )
        assert ModelsService._model_provider_registry.get("cohere.embed-english-v3") == "bedrock"

    @pytest.mark.asyncio
    async def test_does_not_register_bedrock_models_when_region_blank(self, monkeypatch):
        monkeypatch.setattr(
            "config.config_manager.config_manager",
            SimpleNamespace(get_config=lambda: _config(bedrock_region="")),
        )

        service = ModelsService()
        await service.update_model_registry()

        assert "cohere.embed-multilingual-v3" not in ModelsService._model_provider_registry


class TestGetLiteLLMModelNameResolvesBedrock:
    """The #1 correctness risk: a strict=True query-time embed call for a
    configured Bedrock model must resolve, not raise."""

    @pytest.mark.asyncio
    async def test_strict_resolution_produces_bedrock_prefixed_model_string(self, monkeypatch):
        monkeypatch.setattr(
            "config.config_manager.config_manager",
            SimpleNamespace(get_config=lambda: _config(bedrock_region="eu-central-1")),
        )

        service = ModelsService()
        formatted = await service.get_litellm_model_name(
            "cohere.embed-multilingual-v3", strict=True
        )

        assert formatted == "bedrock/cohere.embed-multilingual-v3"

    @pytest.mark.asyncio
    async def test_strict_resolution_raises_when_bedrock_not_configured(self, monkeypatch):
        monkeypatch.setattr(
            "config.config_manager.config_manager",
            SimpleNamespace(get_config=lambda: _config(bedrock_region="")),
        )

        service = ModelsService()
        with pytest.raises(UnknownEmbeddingProvider):
            await service.get_litellm_model_name("cohere.embed-multilingual-v3", strict=True)

    @pytest.mark.asyncio
    async def test_already_prefixed_model_short_circuits_registry(self, monkeypatch):
        """A model name already carrying the "bedrock/" prefix is returned
        as-is without touching the registry at all (matches existing
        behavior for openai/, ollama/, watsonx/, anthropic/)."""
        monkeypatch.setattr(
            "config.config_manager.config_manager",
            SimpleNamespace(get_config=lambda: _config(bedrock_region="")),
        )

        service = ModelsService()
        formatted = await service.get_litellm_model_name(
            "bedrock/cohere.embed-multilingual-v3", strict=True
        )

        assert formatted == "bedrock/cohere.embed-multilingual-v3"

    @pytest.mark.asyncio
    async def test_non_strict_falls_back_to_raw_name_when_unresolved(self, monkeypatch):
        monkeypatch.setattr(
            "config.config_manager.config_manager",
            SimpleNamespace(get_config=lambda: _config(bedrock_region="")),
        )

        service = ModelsService()
        formatted = await service.get_litellm_model_name("cohere.embed-multilingual-v3")

        assert formatted == "cohere.embed-multilingual-v3"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
