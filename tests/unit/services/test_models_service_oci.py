"""Unit tests for OCI Generative AI support in ``ModelsService``.

The most important correctness requirement from the source issue: a query
embedding call resolves its model through
``ModelsService.get_litellm_model_name(model, strict=True)``, which raises
``UnknownEmbeddingProvider`` if the model isn't claimed by any *currently
configured* provider in the registry. Without a matching
``update_model_registry()`` branch, every OCI query-time embed would hard
fail even after every other piece of OCI wiring is correct. These tests
pin that registration path down directly.
"""

from types import SimpleNamespace

import pytest

from services.models_service import KNOWN_PREFIXES, ModelsService, UnknownEmbeddingProvider


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test gets a clean model-provider registry (it's class-level state)."""
    ModelsService._model_provider_registry = {}
    yield
    ModelsService._model_provider_registry = {}


def _config_with_oci(**oci_overrides) -> SimpleNamespace:
    oci_defaults = dict(
        user="",
        fingerprint="",
        tenancy="",
        compartment_id="",
        key="",
        key_file="",
        region="",
        configured=False,
        auth_method="api_key",
    )
    oci_defaults.update(oci_overrides)
    return SimpleNamespace(
        providers=SimpleNamespace(
            openai=SimpleNamespace(api_key=""),
            anthropic=SimpleNamespace(api_key=""),
            ollama=SimpleNamespace(endpoint=""),
            watsonx=SimpleNamespace(api_key="", endpoint="", project_id=""),
            oci=SimpleNamespace(**oci_defaults),
        )
    )


FULL_OCI_CREDS = dict(
    user="ocid1.user.oc1..xxx",
    fingerprint="xx:xx:xx:xx",
    tenancy="ocid1.tenancy.oc1..xxx",
    compartment_id="ocid1.compartment.oc1..xxx",
    key_file="/tmp/oci_key.pem",
)


class TestKnownPrefixes:
    def test_oci_is_a_known_prefix(self):
        assert "oci" in KNOWN_PREFIXES


class TestGetOciModelsStaticList:
    @pytest.mark.asyncio
    async def test_no_language_models(self):
        service = ModelsService()
        result = await service.get_oci_models(update_index=False)
        assert result["language_models"] == []

    @pytest.mark.asyncio
    async def test_embedding_models_shape(self):
        service = ModelsService()
        result = await service.get_oci_models(update_index=False)
        assert result["embedding_models"], "expected at least one embedding model"
        for model in result["embedding_models"]:
            assert set(model.keys()) == {"value", "label", "default"}
            assert isinstance(model["value"], str) and model["value"]
            assert isinstance(model["label"], str) and model["label"]
            assert isinstance(model["default"], bool)

    @pytest.mark.asyncio
    async def test_target_model_is_included_and_default(self):
        service = ModelsService()
        result = await service.get_oci_models(update_index=False)
        values = {m["value"]: m for m in result["embedding_models"]}
        assert "cohere.embed-multilingual-v3.0" in values
        assert values["cohere.embed-multilingual-v3.0"]["default"] is True

    @pytest.mark.asyncio
    async def test_exactly_one_default(self):
        service = ModelsService()
        result = await service.get_oci_models(update_index=False)
        defaults = [m for m in result["embedding_models"] if m["default"]]
        assert len(defaults) == 1

    @pytest.mark.asyncio
    async def test_image_variants_excluded(self):
        service = ModelsService()
        result = await service.get_oci_models(update_index=False)
        values = {m["value"] for m in result["embedding_models"]}
        assert not any("image" in v for v in values)

    @pytest.mark.asyncio
    async def test_no_live_http_call(self, monkeypatch):
        """Static list — must not touch the network at all."""
        import httpx

        async def _boom(*args, **kwargs):
            raise AssertionError("get_oci_models must not make live HTTP calls")

        monkeypatch.setattr(httpx.AsyncClient, "get", _boom)
        monkeypatch.setattr(httpx.AsyncClient, "post", _boom)

        service = ModelsService()
        result = await service.get_oci_models(update_index=False)
        assert result["embedding_models"]

    @pytest.mark.asyncio
    async def test_update_index_registers_models(self):
        service = ModelsService()
        await service.get_oci_models(update_index=True)
        assert (
            ModelsService._model_provider_registry.get("cohere.embed-multilingual-v3.0") == "oci"
        )


class TestUpdateModelRegistryOciGating:
    @pytest.mark.asyncio
    async def test_fully_configured_oci_registers_models(self, monkeypatch):
        config = _config_with_oci(**FULL_OCI_CREDS)
        monkeypatch.setattr(
            "config.config_manager.config_manager.get_config", lambda: config
        )

        service = ModelsService()
        await service.update_model_registry()

        assert (
            ModelsService._model_provider_registry.get("cohere.embed-multilingual-v3.0") == "oci"
        )

    @pytest.mark.asyncio
    async def test_missing_compartment_id_does_not_register(self, monkeypatch):
        creds = dict(FULL_OCI_CREDS)
        creds.pop("compartment_id")
        config = _config_with_oci(**creds)
        monkeypatch.setattr(
            "config.config_manager.config_manager.get_config", lambda: config
        )

        service = ModelsService()
        await service.update_model_registry()

        assert "cohere.embed-multilingual-v3.0" not in ModelsService._model_provider_registry

    @pytest.mark.asyncio
    async def test_missing_key_and_key_file_does_not_register(self, monkeypatch):
        creds = dict(FULL_OCI_CREDS)
        creds.pop("key_file")
        config = _config_with_oci(**creds)
        monkeypatch.setattr(
            "config.config_manager.config_manager.get_config", lambda: config
        )

        service = ModelsService()
        await service.update_model_registry()

        assert "cohere.embed-multilingual-v3.0" not in ModelsService._model_provider_registry

    @pytest.mark.asyncio
    async def test_inline_key_satisfies_the_key_requirement(self, monkeypatch):
        creds = dict(FULL_OCI_CREDS)
        del creds["key_file"]
        creds["key"] = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
        config = _config_with_oci(**creds)
        monkeypatch.setattr(
            "config.config_manager.config_manager.get_config", lambda: config
        )

        service = ModelsService()
        await service.update_model_registry()

        assert (
            ModelsService._model_provider_registry.get("cohere.embed-multilingual-v3.0") == "oci"
        )

    @pytest.mark.asyncio
    async def test_unconfigured_oci_does_not_register(self, monkeypatch):
        config = _config_with_oci()  # all blank
        monkeypatch.setattr(
            "config.config_manager.config_manager.get_config", lambda: config
        )

        service = ModelsService()
        await service.update_model_registry()

        assert ModelsService._model_provider_registry == {}

    @pytest.mark.asyncio
    async def test_instance_principal_registers_without_key_fields(self, monkeypatch):
        # No api_key fields set at all -- the point of this test is that
        # registration must NOT require user/fingerprint/tenancy/key(_file)
        # when auth_method is instance_principal. update_model_registry's
        # gate deliberately never calls build_oci_signer() itself (that
        # would trigger a live IMDS call on every registry refresh), so
        # there's no signer construction to mock here.
        config = _config_with_oci(
            auth_method="instance_principal",
            compartment_id="ocid1.compartment.oc1..aaa",
            region="us-ashburn-1",
        )
        monkeypatch.setattr(
            "config.config_manager.config_manager.get_config", lambda: config
        )

        service = ModelsService()
        await service.update_model_registry()

        assert "cohere.embed-multilingual-v3.0" in ModelsService._model_provider_registry
        assert ModelsService._model_provider_registry["cohere.embed-multilingual-v3.0"] == "oci"


class TestGetLitellmModelNameResolvesOciThroughRegistry:
    """The #1 correctness risk from the source issue: a search-time embed
    call must resolve the OCI provider via the registry under strict=True,
    or it raises UnknownEmbeddingProvider and the query hard-fails.
    """

    @pytest.mark.asyncio
    async def test_strict_resolution_succeeds_once_registered(self, monkeypatch):
        config = _config_with_oci(**FULL_OCI_CREDS)
        monkeypatch.setattr(
            "config.config_manager.config_manager.get_config", lambda: config
        )

        service = ModelsService()
        formatted = await service.get_litellm_model_name(
            "cohere.embed-multilingual-v3.0", strict=True
        )

        assert formatted == "oci/cohere.embed-multilingual-v3.0"

    @pytest.mark.asyncio
    async def test_strict_resolution_raises_when_oci_not_configured(self, monkeypatch):
        config = _config_with_oci()  # not configured
        monkeypatch.setattr(
            "config.config_manager.config_manager.get_config", lambda: config
        )

        service = ModelsService()
        with pytest.raises(UnknownEmbeddingProvider):
            await service.get_litellm_model_name("cohere.embed-multilingual-v3.0", strict=True)

    @pytest.mark.asyncio
    async def test_already_prefixed_model_short_circuits_without_registry_lookup(self):
        service = ModelsService()
        # No registry population needed -- the oci/ prefix is a KNOWN_PREFIXES
        # short-circuit, returned unchanged.
        formatted = await service.get_litellm_model_name(
            "oci/cohere.embed-multilingual-v3.0", strict=True
        )
        assert formatted == "oci/cohere.embed-multilingual-v3.0"
