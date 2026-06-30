"""Unit tests for auth.jwt_roles.extract_jwt_role_names.

The helper is a pure function that reads env vars on each call, so we drive
it entirely with monkeypatch.setenv.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from auth.jwt_roles import extract_jwt_role_names, jwt_roles_enabled  # noqa: E402


@pytest.fixture(autouse=True)
def _default_role_env(monkeypatch):
    """Reset the role-claim mapping to a known shape for each test."""
    monkeypatch.setenv("OPENRAG_JWT_ROLES_CLAIM", "openrag_roles")
    monkeypatch.setenv("OPENRAG_ROLE_CLAIM_ADMIN", "admin")
    monkeypatch.setenv("OPENRAG_ROLE_CLAIM_DEVELOPER", "manager")
    monkeypatch.setenv("OPENRAG_ROLE_CLAIM_USER", "user")
    monkeypatch.delenv("OPENRAG_ROLE_CLAIM_VIEWER", raising=False)


def test_empty_or_none_claims_returns_empty():
    assert extract_jwt_role_names(None) == []
    assert extract_jwt_role_names({}) == []


def test_missing_claim_returns_empty():
    assert extract_jwt_role_names({"sub": "alice"}) == []


def test_single_admin_role_mapped():
    assert extract_jwt_role_names({"openrag_roles": ["admin"]}) == ["admin"]


def test_manager_claim_maps_to_developer_role():
    """The IdP sends "manager"; the operator maps that to OpenRAG developer."""
    assert extract_jwt_role_names({"openrag_roles": ["manager"]}) == ["developer"]


def test_multiple_roles_preserve_order_and_dedup():
    result = extract_jwt_role_names({"openrag_roles": ["user", "admin", "user"]})
    assert result == ["user", "admin"]


def test_unknown_claim_values_are_skipped(monkeypatch, caplog):
    result = extract_jwt_role_names({"openrag_roles": ["super-duper", "admin", "ghost"]})
    assert result == ["admin"]


def test_string_value_is_rejected(caplog):
    """Strict shape: a string is NOT silently treated as a single role."""
    assert extract_jwt_role_names({"openrag_roles": "admin"}) == []


def test_mixed_list_is_rejected():
    """If any element isn't a string, the whole claim is rejected."""
    assert extract_jwt_role_names({"openrag_roles": ["admin", 42]}) == []


def test_dict_value_is_rejected():
    assert extract_jwt_role_names({"openrag_roles": {"role": "admin"}}) == []


def test_empty_list_returns_empty():
    assert extract_jwt_role_names({"openrag_roles": []}) == []


def test_custom_claim_name(monkeypatch):
    monkeypatch.setenv("OPENRAG_JWT_ROLES_CLAIM", "groups")
    assert extract_jwt_role_names({"groups": ["admin"], "openrag_roles": []}) == ["admin"]


def test_one_claim_value_maps_to_two_openrag_roles(monkeypatch):
    """When the IdP only ships 3 role values, the operator can route a single
    claim value (here "user") to both the OpenRAG user and viewer roles."""
    monkeypatch.setenv("OPENRAG_ROLE_CLAIM_VIEWER", "user")
    result = extract_jwt_role_names({"openrag_roles": ["user"]})
    # Order: user comes first because admin/developer/user/viewer iteration
    # places user's bucket before viewer's.
    assert set(result) == {"user", "viewer"}


def test_viewer_unmapped_means_unreachable():
    """Without OPENRAG_ROLE_CLAIM_VIEWER set, the JWT cannot grant viewer."""
    assert extract_jwt_role_names({"openrag_roles": ["viewer"]}) == []


def test_jwt_roles_enabled_tracks_rbac_enforce(monkeypatch):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "false")
    assert jwt_roles_enabled() is False
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    assert jwt_roles_enabled() is True
