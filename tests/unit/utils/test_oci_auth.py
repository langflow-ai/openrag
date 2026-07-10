"""Unit tests for ``utils.oci_auth.build_oci_signer``.

All OCI SDK signer construction is mocked — no real IMDS or in-cluster
proxymux call is made from a unit test.
"""

from unittest.mock import MagicMock, patch

import pytest

from utils.oci_auth import OCISignerConstructionError, build_oci_signer


class TestBuildOciSignerApiKey:
    def test_returns_none_for_api_key(self):
        assert build_oci_signer("api_key") is None


class TestBuildOciSignerInstancePrincipal:
    @patch("oci.auth.signers.InstancePrincipalsSecurityTokenSigner")
    def test_returns_constructed_signer(self, mock_signer_cls):
        fake_signer = MagicMock()
        mock_signer_cls.return_value = fake_signer

        result = build_oci_signer("instance_principal")

        assert result is fake_signer
        mock_signer_cls.assert_called_once_with()

    @patch("oci.auth.signers.InstancePrincipalsSecurityTokenSigner")
    def test_wraps_construction_failure(self, mock_signer_cls):
        mock_signer_cls.side_effect = Exception("Failed to get security token, IMDS unreachable")

        with pytest.raises(OCISignerConstructionError) as exc_info:
            build_oci_signer("instance_principal")

        message = str(exc_info.value)
        assert "instance principal" in message.lower()
        assert "dynamic group" in message.lower()


class TestBuildOciSignerWorkloadIdentity:
    @patch("oci.auth.signers.get_oke_workload_identity_resource_principal_signer")
    def test_returns_constructed_signer(self, mock_factory):
        fake_signer = MagicMock()
        mock_factory.return_value = fake_signer

        result = build_oci_signer("workload_identity")

        assert result is fake_signer
        mock_factory.assert_called_once_with()

    @patch("oci.auth.signers.get_oke_workload_identity_resource_principal_signer")
    def test_wraps_construction_failure(self, mock_factory):
        mock_factory.side_effect = ValueError("Kubernetes service host was not provided.")

        with pytest.raises(OCISignerConstructionError) as exc_info:
            build_oci_signer("workload_identity")

        message = str(exc_info.value)
        assert "workload identity" in message.lower()
        assert "oke" in message.lower()


class TestBuildOciSignerInvalidMethod:
    def test_unknown_auth_method_raises(self):
        with pytest.raises(ValueError, match="Unknown OCI auth_method"):
            build_oci_signer("not_a_real_method")
