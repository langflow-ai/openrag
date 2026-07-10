"""Unit tests for ``utils.oci_auth.build_oci_signer`` and
``utils.oci_auth.get_cached_oci_signer``.

All OCI SDK signer construction is mocked — no real IMDS or in-cluster
proxymux call is made from a unit test.
"""

from unittest.mock import MagicMock, patch

import pytest

from utils import oci_auth
from utils.oci_auth import OCISignerConstructionError, build_oci_signer, get_cached_oci_signer


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


class TestGetCachedOciSigner:
    @pytest.fixture(autouse=True)
    def _isolate_cache(self):
        """The signer cache is module-level global state -- clear it before
        and after each test so tests don't pollute each other."""
        oci_auth._signer_cache.clear()
        yield
        oci_auth._signer_cache.clear()

    def test_returns_none_for_api_key(self):
        assert get_cached_oci_signer("api_key") is None

    @patch("oci.auth.signers.InstancePrincipalsSecurityTokenSigner")
    def test_second_call_returns_cached_signer_without_reconstructing(self, mock_signer_cls):
        fake_signer = MagicMock()
        mock_signer_cls.return_value = fake_signer

        first = get_cached_oci_signer("instance_principal")
        second = get_cached_oci_signer("instance_principal")

        assert first is fake_signer
        assert second is fake_signer
        mock_signer_cls.assert_called_once_with()
        assert mock_signer_cls.call_count == 1

    @patch("oci.auth.signers.get_oke_workload_identity_resource_principal_signer")
    @patch("oci.auth.signers.InstancePrincipalsSecurityTokenSigner")
    def test_different_auth_methods_cache_independently(
        self, mock_instance_principal_cls, mock_workload_identity_factory
    ):
        instance_principal_signer = MagicMock()
        workload_identity_signer = MagicMock()
        mock_instance_principal_cls.return_value = instance_principal_signer
        mock_workload_identity_factory.return_value = workload_identity_signer

        result_instance_principal = get_cached_oci_signer("instance_principal")
        result_workload_identity = get_cached_oci_signer("workload_identity")

        assert result_instance_principal is instance_principal_signer
        assert result_workload_identity is workload_identity_signer
        assert result_instance_principal is not result_workload_identity

        # Both remain resident and independently cached on repeat calls.
        assert get_cached_oci_signer("instance_principal") is instance_principal_signer
        assert get_cached_oci_signer("workload_identity") is workload_identity_signer
        mock_instance_principal_cls.assert_called_once_with()
        mock_workload_identity_factory.assert_called_once_with()

    @patch("oci.auth.signers.InstancePrincipalsSecurityTokenSigner")
    def test_construction_failure_is_not_cached_and_retries_next_call(self, mock_signer_cls):
        mock_signer_cls.side_effect = Exception("Failed to get security token, IMDS unreachable")

        with pytest.raises(OCISignerConstructionError):
            get_cached_oci_signer("instance_principal")

        with pytest.raises(OCISignerConstructionError):
            get_cached_oci_signer("instance_principal")

        # No permanent lockout: construction was retried, not served stale.
        assert mock_signer_cls.call_count == 2
