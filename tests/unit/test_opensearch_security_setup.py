import copy
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


def _conflict_error():
    from opensearchpy.exceptions import ConflictError

    return ConflictError(
        409,
        '{"status":"CONFLICT","message":"[rolesmapping]: version conflict, required seqNo '
        '[77], primary term [5]. current document has seqNo [81] and primary term [6]"}',
    )


async def _run_setup(mock_client):
    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", MagicMock()),
        patch("yaml.safe_load", side_effect=[_sample_roles(), _sample_mappings()]),
        patch("utils.opensearch_utils.asyncio.sleep", AsyncMock()) as sleep_mock,
    ):
        await setup_opensearch_security(mock_client)
    return sleep_mock


@pytest.mark.asyncio
async def test_setup_opensearch_security_retries_mapping_put_on_version_conflict():
    """Issue #1981: a concurrent rolesmapping write (409) is re-read, re-merged and retried."""
    mock_client = MagicMock()
    puts = []
    state = {
        "mappings": {
            "openrag_user_acl_role": {"users": ["acl-user"], "backend_roles": ["openrag_user"]},
        },
        "conflicted": False,
    }

    async def perform_request(method, path, **kwargs):
        if method == "GET" and path == "/_plugins/_security/api/rolesmapping":
            return copy.deepcopy(state["mappings"])
        if method == "PUT" and path.endswith("/rolesmapping/openrag_user_acl_role"):
            puts.append(kwargs["body"])
            if not state["conflicted"]:
                # Another writer (e.g. startup vs onboarding) lands first.
                state["conflicted"] = True
                state["mappings"]["openrag_user_acl_role"]["users"].append("concurrent-user")
                raise _conflict_error()
        return {"status": "OK"}

    mock_client.transport.perform_request = AsyncMock(side_effect=perform_request)
    mock_client.cluster.health = AsyncMock(return_value={"status": "green"})

    sleep_mock = await _run_setup(mock_client)

    assert len(puts) == 2
    assert puts[0]["users"] == ["acl-user"]
    # The retry merges the configured mapping with the freshly re-read principals.
    assert puts[1]["users"] == ["acl-user", "concurrent-user"]
    assert puts[1]["backend_roles"] == ["openrag_user"]
    sleep_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_setup_opensearch_security_retries_all_access_put_on_version_conflict():
    """The all_access mapping is re-read on retry so a concurrent admin is not dropped."""
    mock_client = MagicMock()
    puts = []
    all_access = {"users": ["existing-admin"], "backend_roles": ["admin"]}

    async def perform_request(method, path, **kwargs):
        if method == "GET" and path == "/_plugins/_security/api/rolesmapping":
            return {}
        if method == "GET" and path == "/_plugins/_security/api/rolesmapping/all_access":
            return {"all_access": copy.deepcopy(all_access)}
        if method == "PUT" and path.endswith("/rolesmapping/all_access"):
            puts.append(kwargs["body"])
            if len(puts) == 1:
                all_access["users"].append("tenant-admin")
                raise _conflict_error()
        return {"status": "OK"}

    mock_client.transport.perform_request = AsyncMock(side_effect=perform_request)
    mock_client.cluster.health = AsyncMock(return_value={"status": "green"})

    await _run_setup(mock_client)

    assert len(puts) == 2
    assert puts[1]["users"] == ["admin", "existing-admin", "tenant-admin"]


@pytest.mark.asyncio
async def test_setup_opensearch_security_retries_role_put_on_version_conflict():
    mock_client = MagicMock()
    role_puts = []

    async def perform_request(method, path, **kwargs):
        if method == "PUT" and path.endswith("/roles/openrag_user_role"):
            role_puts.append(kwargs["body"])
            if len(role_puts) == 1:
                raise _conflict_error()
        return {}

    mock_client.transport.perform_request = AsyncMock(side_effect=perform_request)
    mock_client.cluster.health = AsyncMock(return_value={"status": "green"})

    await _run_setup(mock_client)

    assert len(role_puts) == 2


@pytest.mark.asyncio
async def test_setup_opensearch_security_gives_up_after_bounded_conflict_retries():
    from opensearchpy.exceptions import ConflictError

    from utils.opensearch_utils import SECURITY_API_CONFLICT_MAX_ATTEMPTS

    mock_client = MagicMock()
    mapping_puts = []

    async def perform_request(method, path, **kwargs):
        if method == "PUT" and path.endswith("/rolesmapping/openrag_user_acl_role"):
            mapping_puts.append(kwargs["body"])
            raise _conflict_error()
        return {}

    mock_client.transport.perform_request = AsyncMock(side_effect=perform_request)
    mock_client.cluster.health = AsyncMock(return_value={"status": "green"})

    with pytest.raises(ConflictError):
        await _run_setup(mock_client)

    assert len(mapping_puts) == SECURITY_API_CONFLICT_MAX_ATTEMPTS
