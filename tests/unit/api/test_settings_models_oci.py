"""Unit tests for OCI wiring in ``api.settings.models`` and
``api.settings.helpers``."""

import pytest
from pydantic import ValidationError

from api.settings.helpers import _EMBEDDING_PROVIDER_NAMES, _first_configured_embedding_provider
from api.settings.models import (
    OCIProviderConfig,
    OnboardingBody,
    ProvidersConfig,
    SettingsUpdateBody,
)


class TestEmbeddingProviderRegexAcceptsOci:
    def test_settings_update_body_accepts_oci(self):
        body = SettingsUpdateBody(embedding_provider="oci")
        assert body.embedding_provider == "oci"

    def test_onboarding_body_accepts_oci(self):
        body = OnboardingBody(embedding_provider="oci")
        assert body.embedding_provider == "oci"


class TestOciRequestFields:
    def test_settings_update_body_accepts_oci_credential_fields(self):
        body = SettingsUpdateBody(
            oci_user="ocid1.user.oc1..xxx",
            oci_fingerprint="xx:xx:xx:xx",
            oci_tenancy="ocid1.tenancy.oc1..xxx",
            oci_compartment_id="ocid1.compartment.oc1..xxx",
            oci_key_file="/tmp/key.pem",
            oci_region="us-ashburn-1",
        )
        assert body.oci_user == "ocid1.user.oc1..xxx"
        assert body.oci_compartment_id == "ocid1.compartment.oc1..xxx"

    def test_settings_update_body_accepts_remove_oci_config(self):
        body = SettingsUpdateBody(remove_oci_config=True)
        assert body.remove_oci_config is True

    def test_onboarding_body_accepts_oci_credential_fields(self):
        body = OnboardingBody(oci_user="u", oci_key="pem-content")
        assert body.oci_user == "u"
        assert body.oci_key == "pem-content"

    def test_settings_update_body_accepts_oci_auth_method(self):
        body = SettingsUpdateBody(oci_auth_method="workload_identity")
        assert body.oci_auth_method == "workload_identity"

    def test_onboarding_body_accepts_oci_auth_method(self):
        body = OnboardingBody(oci_auth_method="instance_principal")
        assert body.oci_auth_method == "instance_principal"

    def test_settings_update_body_rejects_invalid_oci_auth_method(self):
        with pytest.raises(ValidationError):
            SettingsUpdateBody(oci_auth_method="invalid")

    def test_onboarding_body_rejects_invalid_oci_auth_method(self):
        with pytest.raises(ValidationError):
            OnboardingBody(oci_auth_method="invalid")

    @pytest.mark.parametrize("auth_method", ["api_key", "instance_principal", "workload_identity"])
    def test_settings_update_body_accepts_all_legal_oci_auth_methods(self, auth_method):
        body = SettingsUpdateBody(oci_auth_method=auth_method)
        assert body.oci_auth_method == auth_method

    @pytest.mark.parametrize("auth_method", ["api_key", "instance_principal", "workload_identity"])
    def test_onboarding_body_accepts_all_legal_oci_auth_methods(self, auth_method):
        body = OnboardingBody(oci_auth_method=auth_method)
        assert body.oci_auth_method == auth_method

    def test_settings_update_body_accepts_omitted_oci_auth_method(self):
        body = SettingsUpdateBody()
        assert body.oci_auth_method is None

    def test_onboarding_body_accepts_omitted_oci_auth_method(self):
        body = OnboardingBody()
        assert body.oci_auth_method is None


class TestOciProviderConfigResponseModel:
    def test_shape_mirrors_watsonx_style(self):
        cfg = OCIProviderConfig(
            has_key=True,
            user="ocid1.user.oc1..xxx",
            tenancy="ocid1.tenancy.oc1..xxx",
            compartment_id="ocid1.compartment.oc1..xxx",
            region="us-ashburn-1",
            configured=True,
        )
        assert cfg.has_key is True
        assert cfg.configured is True

    def test_default_auth_method_is_api_key(self):
        cfg = OCIProviderConfig(
            has_key=True,
            user="ocid1.user.oc1..xxx",
            tenancy="ocid1.tenancy.oc1..xxx",
            compartment_id="ocid1.compartment.oc1..xxx",
            region="us-ashburn-1",
            configured=True,
        )
        assert cfg.auth_method == "api_key"

    def test_oci_provider_config_response_includes_auth_method(self):
        cfg = OCIProviderConfig(
            has_key=False,
            user=None,
            tenancy="t",
            compartment_id="c",
            region="eu-frankfurt-1",
            auth_method="instance_principal",
            configured=True,
        )
        assert cfg.auth_method == "instance_principal"

    def test_providers_config_requires_oci_field(self):
        with pytest.raises(ValidationError):
            ProvidersConfig.model_validate(
                {
                    "openai": {"has_api_key": False, "configured": False},
                    "anthropic": {"has_api_key": False, "configured": False},
                    "watsonx": {
                        "has_api_key": False,
                        "endpoint": None,
                        "project_id": None,
                        "configured": False,
                    },
                    "ollama": {"endpoint": None, "configured": False},
                    # "oci" deliberately omitted
                }
            )


class TestEmbeddingProviderNamesIncludesOci:
    def test_oci_in_embedding_provider_names(self):
        assert "oci" in _EMBEDDING_PROVIDER_NAMES

    def test_first_configured_embedding_provider_can_return_oci(self):
        class Providers:
            openai = type("P", (), {"configured": False})()
            watsonx = type("P", (), {"configured": False})()
            ollama = type("P", (), {"configured": False})()
            oci = type("P", (), {"configured": True})()

        config = type("Config", (), {"providers": Providers()})()
        assert _first_configured_embedding_provider(config, excluding="watsonx") == "oci"
