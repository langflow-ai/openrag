from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.opensearch_utils import setup_opensearch_security


def _sample_roles():
    return {
        "openrag_user_role": {
            "cluster_permissions": ["cluster:monitor/*"],
            "index_permissions": [
                {
                    "index_patterns": ["documents"],
                    "allowed_actions": ["read"],
                    "dls": '{"term":{"owner":"${user.name}"}}',
                }
            ],
        },
        "openrag_user_acl_role": {
            "cluster_permissions": [],
            "index_permissions": [
                {
                    "index_patterns": ["documents"],
                    "allowed_actions": ["read"],
                    "dls": '{"term":{"allowed_users":"${user.name}"}}',
                }
            ],
        },
    }


def _sample_mappings():
    return {
        "openrag_user_role": {
            "users": [],
            "hosts": [],
            "backend_roles": ["openrag_user"],
        },
        "openrag_user_acl_role": {
            "users": [],
            "hosts": [],
            "backend_roles": ["openrag_user"],
        },
        "all_access": {"users": ["admin"]},
    }


@pytest.mark.asyncio
async def test_setup_opensearch_security_applies_acl_role_before_narrowing_legacy_role():
    """ACL role and mapping are verified before the legacy role is narrowed."""
    mock_client = MagicMock()
    requests = []
    existing_mappings = {
        "openrag_user_role": {
            "users": ["direct-user"],
            "hosts": ["legacy-host"],
            "backend_roles": ["legacy_backend_role"],
        },
        "openrag_user_acl_role": {
            "users": ["acl-user"],
            "hosts": [],
            "backend_roles": ["acl_backend_role"],
        },
    }

    async def perform_request(method, path, **kwargs):
        requests.append((method, path, kwargs.get("body")))
        if method == "GET" and path == "/_plugins/_security/api/rolesmapping":
            return existing_mappings
        if method == "GET" and path == "/_plugins/_security/api/rolesmapping/all_access":
            return {"all_access": {"users": ["existing-admin"], "backend_roles": ["admin"]}}
        return {"status": "OK", "message": "Success"}

    mock_client.transport.perform_request = AsyncMock(side_effect=perform_request)
    mock_client.cluster.health = AsyncMock(return_value={"status": "green"})

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", MagicMock()),
        patch("yaml.safe_load", side_effect=[_sample_roles(), _sample_mappings()]),
    ):
        await setup_opensearch_security(mock_client)

    request_paths = [(method, path) for method, path, _ in requests]
    assert request_paths.index(
        ("PUT", "/_plugins/_security/api/roles/openrag_user_acl_role")
    ) < request_paths.index(("PUT", "/_plugins/_security/api/roles/openrag_user_role"))
    assert request_paths.index(
        ("PUT", "/_plugins/_security/api/rolesmapping/openrag_user_acl_role")
    ) < request_paths.index(("PUT", "/_plugins/_security/api/roles/openrag_user_role"))
    assert request_paths.index(
        ("GET", "/_plugins/_security/api/roles/openrag_user_acl_role")
    ) < request_paths.index(("PUT", "/_plugins/_security/api/roles/openrag_user_role"))
    assert request_paths.index(
        ("GET", "/_plugins/_security/api/rolesmapping/openrag_user_acl_role")
    ) < request_paths.index(("PUT", "/_plugins/_security/api/roles/openrag_user_role"))

    acl_mapping_put = next(
        body
        for method, path, body in requests
        if method == "PUT" and path.endswith("/rolesmapping/openrag_user_acl_role")
    )
    assert acl_mapping_put["users"] == ["direct-user", "acl-user"]
    assert acl_mapping_put["hosts"] == ["legacy-host"]
    assert acl_mapping_put["backend_roles"] == [
        "openrag_user",
        "legacy_backend_role",
        "acl_backend_role",
    ]

    legacy_mapping_put = next(
        body
        for method, path, body in requests
        if method == "PUT" and path.endswith("/rolesmapping/openrag_user_role")
    )
    assert legacy_mapping_put["users"] == ["direct-user"]
    assert legacy_mapping_put["hosts"] == ["legacy-host"]
    assert legacy_mapping_put["backend_roles"] == [
        "openrag_user",
        "legacy_backend_role",
    ]


@pytest.mark.asyncio
async def test_setup_opensearch_security_skips_auth_error_before_mutation():
    """Auth/security errors are graceful only before any security state is mutated."""
    mock_client = MagicMock()
    mock_client.transport.perform_request = AsyncMock(side_effect=Exception("401 Unauthorized"))
    mock_client.cluster.health = AsyncMock()

    await setup_opensearch_security(mock_client)

    assert mock_client.transport.perform_request.call_count == 1
    mock_client.cluster.health.assert_not_called()


@pytest.mark.asyncio
async def test_setup_opensearch_security_raises_security_error_after_partial_migration():
    """A post-ACL failure must fail startup instead of hiding partial security state."""
    mock_client = MagicMock()
    requests = []

    async def perform_request(method, path, **kwargs):
        requests.append((method, path))
        if method == "PUT" and path == "/_plugins/_security/api/roles/openrag_user_role":
            raise Exception("403 forbidden")
        return {}

    mock_client.transport.perform_request = AsyncMock(side_effect=perform_request)
    mock_client.cluster.health = AsyncMock(return_value={"status": "green"})

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", MagicMock()),
        patch("yaml.safe_load", side_effect=[_sample_roles(), _sample_mappings()]),
    ):
        with pytest.raises(Exception, match="403 forbidden"):
            await setup_opensearch_security(mock_client)

    assert ("PUT", "/_plugins/_security/api/rolesmapping/openrag_user_acl_role") in requests
    assert ("GET", "/_plugins/_security/api/rolesmapping/openrag_user_acl_role") in requests


@pytest.mark.asyncio
async def test_setup_opensearch_security_missing_files():
    """Test that missing configuration files raise FileNotFoundError."""
    mock_client = MagicMock()
    mock_client.transport.perform_request = AsyncMock(return_value={})
    mock_client.cluster.health = AsyncMock(return_value={"status": "green"})

    with patch("os.path.exists", return_value=False):
        with pytest.raises(FileNotFoundError):
            await setup_opensearch_security(mock_client)
