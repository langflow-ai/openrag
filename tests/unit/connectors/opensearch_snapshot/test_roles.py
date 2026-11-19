from __future__ import annotations

import pytest

from connectors.opensearch_snapshot import roles
from connectors.opensearch_snapshot.roles import RoleError

from ._fakes import ApiError, FakeOpenSearch

SLUG = "abcdefghij"


@pytest.fixture(autouse=True)
def _no_skip(monkeypatch):
    monkeypatch.setenv("OPENRAG_SKIP_OS_SECURITY_SETUP", "false")
    monkeypatch.delenv("OPENRAG_SNAPSHOT_SHARED_BACKEND_ROLE", raising=False)


class ExplodingClient:
    """Any attribute access is a security-write call that must not happen."""

    def __getattr__(self, name):
        raise AssertionError(f"unexpected OpenSearch call: {name}")


def test_role_body_is_scoped_to_the_import_and_read_only():
    body = roles.role_body(SLUG)
    perms = body["index_permissions"]
    assert perms == [
        {
            "index_patterns": [f"ds_{SLUG}_*"],
            "allowed_actions": ["read", "indices:admin/mappings/get"],
        }
    ]
    assert body["cluster_permissions"] == []
    assert "dls" not in str(body)


def test_role_mapping_private_and_shared(monkeypatch):
    assert roles.role_mapping_body("alice", False)["users"] == ["alice"]
    assert "backend_roles" not in roles.role_mapping_body("alice", False)
    assert roles.role_mapping_body(None, True)["backend_roles"] == ["openrag_user"]
    assert "users" not in roles.role_mapping_body("alice", True)
    monkeypatch.setenv("OPENRAG_SNAPSHOT_SHARED_BACKEND_ROLE", "team_role")
    assert roles.role_mapping_body("alice", True)["backend_roles"] == ["team_role"]
    with pytest.raises(ValueError):
        roles.role_mapping_body(None, False)
    with pytest.raises(ValueError):
        roles.role_mapping_body("", False)


def test_role_json():
    doc = roles.role_json(SLUG, "alice", False)
    assert doc["role_name"] == doc["role_mapping_name"] == f"openrag_ds_{SLUG}"
    assert doc["role"] == roles.role_body(SLUG) and doc["role_mapping"]["users"] == ["alice"]


@pytest.mark.asyncio
async def test_apply_role_writes_role_then_mapping():
    os_admin = FakeOpenSearch()
    doc = await roles.apply_role(os_admin, SLUG, principal="alice", shared=False)
    calls = [c[1] for c in os_admin.calls if c[0] == "perform_request"]
    assert [(c["method"], c["path"]) for c in calls] == [
        ("PUT", f"/_plugins/_security/api/roles/openrag_ds_{SLUG}"),
        ("PUT", f"/_plugins/_security/api/rolesmapping/openrag_ds_{SLUG}"),
    ]
    assert calls[0]["body"] == roles.role_body(SLUG) and calls[1]["body"]["users"] == ["alice"]
    assert doc == roles.role_json(SLUG, "alice", False)


@pytest.mark.asyncio
async def test_apply_role_failure_is_role_error():
    os_admin = FakeOpenSearch()
    os_admin.perform_error = ApiError(500, "security index not ready")
    with pytest.raises(RoleError) as err:
        await roles.apply_role(os_admin, SLUG, principal="alice", shared=False)
    assert "not ready" not in str(err.value)


@pytest.mark.asyncio
async def test_remove_role_deletes_mapping_then_role_and_ignores_404():
    os_admin = FakeOpenSearch()
    await roles.remove_role(os_admin, SLUG)
    assert [(c[1]["method"], c[1]["path"]) for c in os_admin.calls] == [
        ("DELETE", f"/_plugins/_security/api/rolesmapping/openrag_ds_{SLUG}"),
        ("DELETE", f"/_plugins/_security/api/roles/openrag_ds_{SLUG}"),
    ]
    os_admin.perform_error = ApiError(404, "NOT_FOUND")
    await roles.remove_role(os_admin, SLUG)
    os_admin.perform_error = ApiError(500, "bad")
    with pytest.raises(RoleError):
        await roles.remove_role(os_admin, SLUG)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE"])
async def test_skip_setting_makes_zero_security_calls(monkeypatch, value):
    monkeypatch.setenv("OPENRAG_SKIP_OS_SECURITY_SETUP", value)
    assert roles.security_managed_externally()
    client = ExplodingClient()
    private = await roles.apply_role(client, SLUG, principal="alice", shared=False)
    shared = await roles.apply_role(client, SLUG, principal=None, shared=True)
    await roles.remove_role(client, SLUG)
    assert private == roles.role_json(SLUG, "alice", False)
    assert shared["role_mapping"]["backend_roles"] == ["openrag_user"]


def test_skip_default_comes_from_settings_when_env_unset(monkeypatch):
    monkeypatch.delenv("OPENRAG_SKIP_OS_SECURITY_SETUP")
    monkeypatch.setattr(roles.app_settings, "OPENRAG_SKIP_OS_SECURITY_SETUP", True)
    assert roles.security_managed_externally()
    monkeypatch.setattr(roles.app_settings, "OPENRAG_SKIP_OS_SECURITY_SETUP", False)
    assert not roles.security_managed_externally()


@pytest.mark.asyncio
async def test_lookup_principal_uses_authinfo():
    client = FakeOpenSearch()
    client.perform_result = {
        "user": "User [name=alice, backend_roles=[openrag_user]]",
        "user_name": "alice",
    }
    assert await roles.lookup_principal(client) == "alice"
    assert (
        client.calls[0][1]["path"] == "/_plugins/_security/authinfo"
        and client.calls[0][1]["method"] == "GET"
    )
    client.perform_result = {"user": "anonymous"}
    with pytest.raises(RoleError):
        await roles.lookup_principal(client)
    client.perform_result = None
    with pytest.raises(RoleError):
        await roles.lookup_principal(client)
    client.perform_error = ApiError(401, "unauthorized")
    with pytest.raises(RoleError):
        await roles.lookup_principal(client)
