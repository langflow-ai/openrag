"""Unit tests for the ``oci`` branch of ``GET /provider/health``.

Confirms the credential fields ``check_provider_health`` extracts via
``getattr(provider_config, "user"/"fingerprint"/..., None)`` actually reach
``_test_oci_credential_shape`` — a bug here would silently no-op the health
check for OCI (empty getattr results always look "unset", which is a false
positive, not a crash) instead of reporting whatever's actually wrong.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.provider_health import check_provider_health


def _oci_config(**overrides):
    defaults = dict(
        user="ocid1.user.oc1..xxx",
        fingerprint="xx:xx:xx:xx",
        tenancy="ocid1.tenancy.oc1..xxx",
        compartment_id="ocid1.compartment.oc1..xxx",
        key="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
        key_file="",
        region="us-ashburn-1",
        auth_method="api_key",
        configured=True,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _config_with_oci(oci_config):
    providers = SimpleNamespace(oci=oci_config)

    def get_provider_config(name):
        if name == "oci":
            return oci_config
        raise ValueError(f"Unknown provider: {name}")

    providers.get_provider_config = get_provider_config
    return SimpleNamespace(
        providers=providers,
        agent=SimpleNamespace(llm_provider="openai", llm_model="gpt-4o-mini"),
        knowledge=SimpleNamespace(embedding_provider="oci", embedding_model="cohere.embed-multilingual-v3.0"),
    )


def _body(response) -> dict:
    return json.loads(bytes(response.body))


class TestCheckProviderHealthOciExplicit:
    @pytest.mark.asyncio
    async def test_valid_oci_credentials_report_healthy(self, monkeypatch):
        config = _config_with_oci(_oci_config())
        monkeypatch.setattr("api.provider_health.get_openrag_config", lambda: config)

        response = await check_provider_health(provider="oci", test_completion=False, user=None)

        assert response.status_code == 200
        assert _body(response)["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_missing_credentials_report_unhealthy(self, monkeypatch):
        config = _config_with_oci(
            _oci_config(user="", fingerprint="", tenancy="", compartment_id="", key="", key_file="")
        )
        monkeypatch.setattr("api.provider_health.get_openrag_config", lambda: config)

        response = await check_provider_health(provider="oci", test_completion=False, user=None)

        assert response.status_code == 503
        assert _body(response)["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_oci_is_accepted_as_a_valid_provider_name(self, monkeypatch):
        config = _config_with_oci(_oci_config())
        monkeypatch.setattr("api.provider_health.get_openrag_config", lambda: config)

        response = await check_provider_health(provider="oci", test_completion=False, user=None)

        # Would be a 400 "Invalid provider" if "oci" weren't in valid_providers.
        assert response.status_code != 400


class TestCheckProviderHealthOciAuthMethod:
    @pytest.mark.asyncio
    async def test_instance_principal_auth_method_is_forwarded(self, monkeypatch):
        """Regression guard for the oci_auth_method local var check_provider_health
        derives via getattr(provider_config, "auth_method", None): without it (or
        with a stale test double missing the field), the check falls back to None,
        which _test_oci_signer_construction rejects as an unknown auth_method
        instead of dispatching to the signer-construction check."""
        config = _config_with_oci(
            _oci_config(
                user="", fingerprint="", tenancy="", key="", key_file="",
                auth_method="instance_principal",
            )
        )
        monkeypatch.setattr("api.provider_health.get_openrag_config", lambda: config)

        with patch("api.provider_validation._test_oci_signer_construction") as mock_signer:
            response = await check_provider_health(provider="oci", test_completion=False, user=None)

        mock_signer.assert_called_once_with("instance_principal")
        assert response.status_code == 200
        assert _body(response)["status"] == "healthy"
