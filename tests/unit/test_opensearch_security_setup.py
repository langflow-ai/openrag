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


async def _run_setup_and_get_acl_mapping_put(monkeypatch, *, no_auth, no_auth_connectors):
    monkeypatch.setattr("config.settings.is_no_auth_mode", lambda: no_auth)
    monkeypatch.setattr("config.settings.has_no_auth_connectors", lambda: no_auth_connectors)

    mock_client = MagicMock()
    requests = []
    existing_mappings = {
        "openrag_user_role": {"backend_roles": ["openrag_user", "custom_role"]},
    }

    async def perform_request(method, path, **kwargs):
        requests.append((method, path, kwargs.get("body")))
        if method == "GET" and path == "/_plugins/_security/api/rolesmapping":
            return existing_mappings
        if method == "GET" and path == "/_plugins/_security/api/rolesmapping/all_access":
            return {"all_access": {"users": ["admin"], "backend_roles": ["admin"]}}
        return {"status": "OK", "message": "Success"}

    mock_client.transport.perform_request = AsyncMock(side_effect=perform_request)
    mock_client.cluster.health = AsyncMock(return_value={"status": "green"})

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", MagicMock()),
        patch("yaml.safe_load", side_effect=[_sample_roles(), _sample_mappings()]),
    ):
        await setup_opensearch_security(mock_client)

    return next(
        body
        for method, path, body in requests
        if method == "PUT" and path.endswith("/rolesmapping/openrag_user_acl_role")
    )


@pytest.mark.asyncio
async def test_no_auth_mode_does_not_map_default_users_to_acl_role(monkeypatch):
    """The ACL role's terms lookup breaks hybrid under DLS; no-auth has no connector ACLs."""
    acl_mapping = await _run_setup_and_get_acl_mapping_put(
        monkeypatch, no_auth=True, no_auth_connectors=False
    )

    assert "openrag_user" not in acl_mapping["backend_roles"]
    assert "custom_role" in acl_mapping["backend_roles"]


@pytest.mark.asyncio
async def test_no_auth_mode_with_dev_bucket_connector_keeps_acl_role(monkeypatch):
    acl_mapping = await _run_setup_and_get_acl_mapping_put(
        monkeypatch, no_auth=True, no_auth_connectors=True
    )

    assert "openrag_user" in acl_mapping["backend_roles"]


@pytest.mark.asyncio
async def test_auth_mode_maps_default_users_to_acl_role(monkeypatch):
    acl_mapping = await _run_setup_and_get_acl_mapping_put(
        monkeypatch, no_auth=False, no_auth_connectors=False
    )

    assert "openrag_user" in acl_mapping["backend_roles"]


@pytest.mark.asyncio
async def test_setup_opensearch_security_applies_acl_role_before_narrowing_legacy_role(
    monkeypatch,
):
    """ACL role and mapping are verified before the legacy role is narrowed."""
    monkeypatch.setattr("config.settings.is_no_auth_mode", lambda: False)
    mock_client = MagicMock()
    requests = []
    existing_mappings = {
        "openrag_user_role": {
            "users": ["direct-user"],
            "hosts": ["legacy-host"],
            "backend_roles": ["legacy_backend_role"],
            "and_backend_roles": ["legacy_and_role"],
            "hidden": False,
            "reserved": False,
        },
        "openrag_user_acl_role": {
            "users": ["acl-user"],
            "hosts": [],
            "backend_roles": ["acl_backend_role"],
            "hidden": False,
            "reserved": False,
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
    assert acl_mapping_put["and_backend_roles"] == ["legacy_and_role"]
    assert "hidden" not in acl_mapping_put
    assert "reserved" not in acl_mapping_put

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
    assert legacy_mapping_put["and_backend_roles"] == ["legacy_and_role"]
    assert "hidden" not in legacy_mapping_put
    assert "reserved" not in legacy_mapping_put


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
async def test_setup_opensearch_security_aborts_on_transient_mapping_read_failure():
    """Without current mappings, setup cannot safely preserve customized principals."""
    mock_client = MagicMock()
    mock_client.transport.perform_request = AsyncMock(
        side_effect=Exception("503 Service Unavailable")
    )
    mock_client.cluster.health = AsyncMock()

    with pytest.raises(Exception, match="503 Service Unavailable"):
        await setup_opensearch_security(mock_client)

    mock_client.transport.perform_request.assert_awaited_once_with(
        "GET", "/_plugins/_security/api/rolesmapping"
    )
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
