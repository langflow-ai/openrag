"""Unit tests for OCI credential-shape validation in ``api.provider_validation``.

OCI Generative AI authenticates via a per-request RSA-SHA256 HTTP Signing
Scheme rather than a bearer token or a simple API key, so — unlike the other
providers' lightweight health checks — this deliberately does NOT make a
live network call. It validates that the credential set is shaped
correctly (the same fields litellm's own OCI ``validate_environment()``
requires before it will even attempt to sign a request), catching obviously
broken configuration before it reaches litellm.
"""

from unittest.mock import MagicMock, patch

import pytest

import api.provider_validation as provider_validation
from api.provider_validation import (
    OCISignerConstructionError,
    _test_oci_credential_shape,
    _test_oci_signer_construction,
    validate_provider_setup,
)
from api.provider_validation import test_lightweight_health as run_lightweight_health

VALID_KWARGS = dict(
    oci_user="ocid1.user.oc1..xxx",
    oci_fingerprint="xx:xx:xx:xx",
    oci_tenancy="ocid1.tenancy.oc1..xxx",
    oci_compartment_id="ocid1.compartment.oc1..xxx",
)


class TestOciCredentialShapeInlineKey:
    @pytest.mark.asyncio
    async def test_valid_inline_pem_key_passes(self):
        await _test_oci_credential_shape(
            **VALID_KWARGS,
            oci_key="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
            oci_key_file=None,
        )

    @pytest.mark.asyncio
    async def test_inline_key_without_pem_marker_fails(self):
        with pytest.raises(Exception, match="does not look like a PEM private key"):
            await _test_oci_credential_shape(
                **VALID_KWARGS, oci_key="not-a-pem-key", oci_key_file=None
            )

    @pytest.mark.asyncio
    async def test_both_key_and_key_file_set_warns_and_prefers_inline_key(
        self, tmp_path, monkeypatch
    ):
        """.env.example says provide exactly one of OCI_KEY_FILE or OCI_KEY.
        When both are set, oci_key silently wins (precedence unchanged by
        this test) but a warning must be logged so misconfiguration is
        visible instead of silent."""
        mock_logger = MagicMock()
        monkeypatch.setattr(provider_validation, "logger", mock_logger)

        key_file = tmp_path / "oci_key.pem"
        key_file.write_text("-----BEGIN PRIVATE KEY-----\nunused\n-----END PRIVATE KEY-----")

        await _test_oci_credential_shape(
            **VALID_KWARGS,
            oci_key="-----BEGIN PRIVATE KEY-----\ninline\n-----END PRIVATE KEY-----",
            oci_key_file=str(key_file),
        )

        assert mock_logger.warning.called
        warning_message = mock_logger.warning.call_args[0][0]
        assert "oci_key" in warning_message
        assert "oci_key_file" in warning_message

    @pytest.mark.asyncio
    async def test_only_inline_key_set_does_not_warn(self, monkeypatch):
        mock_logger = MagicMock()
        monkeypatch.setattr(provider_validation, "logger", mock_logger)

        await _test_oci_credential_shape(
            **VALID_KWARGS,
            oci_key="-----BEGIN PRIVATE KEY-----\ninline\n-----END PRIVATE KEY-----",
            oci_key_file=None,
        )

        mock_logger.warning.assert_not_called()


class TestOciCredentialShapeKeyFile:
    @pytest.mark.asyncio
    async def test_valid_key_file_passes(self, tmp_path):
        key_file = tmp_path / "oci_key.pem"
        key_file.write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----")

        await _test_oci_credential_shape(
            **VALID_KWARGS, oci_key=None, oci_key_file=str(key_file)
        )

    @pytest.mark.asyncio
    async def test_nonexistent_key_file_fails(self, tmp_path):
        missing = tmp_path / "does_not_exist.pem"
        with pytest.raises(Exception, match="does not exist"):
            await _test_oci_credential_shape(
                **VALID_KWARGS, oci_key=None, oci_key_file=str(missing)
            )

    @pytest.mark.asyncio
    async def test_key_file_without_pem_marker_fails(self, tmp_path):
        key_file = tmp_path / "not_a_key.pem"
        key_file.write_text("just some text, not a key")

        with pytest.raises(Exception, match="does not look like a PEM private key"):
            await _test_oci_credential_shape(
                **VALID_KWARGS, oci_key=None, oci_key_file=str(key_file)
            )


class TestOciCredentialShapeMissingFields:
    @pytest.mark.asyncio
    async def test_missing_user_fails(self):
        kwargs = dict(VALID_KWARGS)
        kwargs["oci_user"] = None
        with pytest.raises(Exception, match="user"):
            await _test_oci_credential_shape(**kwargs, oci_key="pem", oci_key_file=None)

    @pytest.mark.asyncio
    async def test_missing_fingerprint_fails(self):
        kwargs = dict(VALID_KWARGS)
        kwargs["oci_fingerprint"] = None
        with pytest.raises(Exception, match="fingerprint"):
            await _test_oci_credential_shape(**kwargs, oci_key="pem", oci_key_file=None)

    @pytest.mark.asyncio
    async def test_missing_tenancy_fails(self):
        kwargs = dict(VALID_KWARGS)
        kwargs["oci_tenancy"] = None
        with pytest.raises(Exception, match="tenancy"):
            await _test_oci_credential_shape(**kwargs, oci_key="pem", oci_key_file=None)

    @pytest.mark.asyncio
    async def test_missing_compartment_id_fails(self):
        kwargs = dict(VALID_KWARGS)
        kwargs["oci_compartment_id"] = None
        with pytest.raises(Exception, match="compartment_id"):
            await _test_oci_credential_shape(**kwargs, oci_key="pem", oci_key_file=None)

    @pytest.mark.asyncio
    async def test_missing_key_and_key_file_fails(self):
        with pytest.raises(Exception, match="oci_key"):
            await _test_oci_credential_shape(**VALID_KWARGS, oci_key=None, oci_key_file=None)

    @pytest.mark.asyncio
    async def test_all_fields_missing_reports_all(self):
        with pytest.raises(Exception, match="user, fingerprint, tenancy, compartment_id"):
            await _test_oci_credential_shape()


class TestOciDispatchThroughLightweightHealth:
    @pytest.mark.asyncio
    async def test_dispatches_to_oci_shape_check(self, tmp_path):
        key_file = tmp_path / "oci_key.pem"
        key_file.write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----")

        # Should not raise -- proves the "oci" branch in test_lightweight_health
        # forwards the oci_* kwargs correctly.
        await run_lightweight_health(
            provider="oci",
            oci_key_file=str(key_file),
            **VALID_KWARGS,
        )

    @pytest.mark.asyncio
    async def test_dispatches_via_validate_provider_setup(self, tmp_path):
        key_file = tmp_path / "oci_key.pem"
        key_file.write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----")

        await validate_provider_setup(
            provider="oci",
            test_completion=False,
            oci_key_file=str(key_file),
            **VALID_KWARGS,
        )

    @pytest.mark.asyncio
    async def test_validate_provider_setup_propagates_shape_errors(self):
        with pytest.raises(Exception, match="OCI configuration"):
            await validate_provider_setup(provider="oci", test_completion=False)


class TestOciSignerConstructionValidation:
    # Patched at "oci.auth.signers.*" (the real SDK module), not
    # "utils.oci_auth.oci...": build_oci_signer() imports `oci.auth.signers`
    # locally inside its function body, so that name is never bound as a
    # module-level attribute of utils.oci_auth for mock.patch's dotted-path
    # lookup to find. Patching the real oci.auth.signers module directly (as
    # tests/unit/utils/test_oci_auth.py already does for build_oci_signer
    # itself) is the pattern that actually intercepts the call.
    COMPARTMENT_ID = "ocid1.compartment.oc1..xxx"

    @pytest.mark.asyncio
    @patch("oci.auth.signers.InstancePrincipalsSecurityTokenSigner")
    async def test_instance_principal_success(self, mock_signer_cls):
        mock_signer_cls.return_value = MagicMock()
        # must not raise
        await _test_oci_signer_construction("instance_principal", self.COMPARTMENT_ID)

    @pytest.mark.asyncio
    @patch("oci.auth.signers.InstancePrincipalsSecurityTokenSigner")
    async def test_instance_principal_failure_raises(self, mock_signer_cls):
        mock_signer_cls.side_effect = Exception("not on OCI compute")
        with pytest.raises(OCISignerConstructionError):
            await _test_oci_signer_construction("instance_principal", self.COMPARTMENT_ID)

    @pytest.mark.asyncio
    @patch("oci.auth.signers.get_oke_workload_identity_resource_principal_signer")
    async def test_workload_identity_success(self, mock_factory):
        mock_factory.return_value = MagicMock()
        # must not raise
        await _test_oci_signer_construction("workload_identity", self.COMPARTMENT_ID)

    # compartment_id scopes which resource the embed call targets, not how the
    # request is signed, so the signer path never touches it -- but litellm
    # requires oci_compartment_id on every embedText call regardless of auth
    # method, and utils.embedding_kwargs.oci_credential_kwargs omits the kwarg
    # entirely when it's empty. Without the check below, an
    # instance_principal/workload_identity setup with no compartment_id passes
    # onboarding and settings validation and only fails at the first real
    # embedding call.
    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth_method", ["instance_principal", "workload_identity"])
    @pytest.mark.parametrize("compartment_id", [None, ""])
    @patch("oci.auth.signers.get_oke_workload_identity_resource_principal_signer")
    @patch("oci.auth.signers.InstancePrincipalsSecurityTokenSigner")
    async def test_missing_compartment_id_rejected(
        self, mock_signer_cls, mock_factory, auth_method, compartment_id
    ):
        mock_signer_cls.return_value = MagicMock()
        mock_factory.return_value = MagicMock()

        with pytest.raises(Exception, match="compartment_id"):
            await _test_oci_signer_construction(auth_method, compartment_id)

        # Rejected before any instance-metadata / proxymux round-trip.
        mock_signer_cls.assert_not_called()
        mock_factory.assert_not_called()


class TestValidateProviderSetupOciAuthMethodDispatch:
    @pytest.mark.asyncio
    @patch("api.provider_validation._test_oci_signer_construction")
    @patch("api.provider_validation._test_oci_credential_shape")
    async def test_api_key_uses_credential_shape_check(self, mock_shape, mock_signer):
        await run_lightweight_health(
            provider="oci",
            oci_auth_method="api_key",
            oci_user="u", oci_fingerprint="f", oci_tenancy="t",
            oci_compartment_id="c", oci_key="-----BEGIN PRIVATE KEY-----",
        )
        mock_shape.assert_called_once()
        mock_signer.assert_not_called()

    @pytest.mark.asyncio
    @patch("api.provider_validation._test_oci_signer_construction")
    @patch("api.provider_validation._test_oci_credential_shape")
    async def test_instance_principal_uses_signer_construction_check(self, mock_shape, mock_signer):
        await run_lightweight_health(
            provider="oci",
            oci_auth_method="instance_principal",
            oci_compartment_id="ocid1.compartment.oc1..xxx",
        )
        mock_signer.assert_called_once_with("instance_principal", "ocid1.compartment.oc1..xxx")
        mock_shape.assert_not_called()
