"""JWT-in-header auth on the /v1 (API-key) surface.

Covers the shared role-staging helper ``_stage_jwt_roles`` and the JWT-header
branch of ``get_api_key_user_async`` in ``src/dependencies.py``.

The branch resolves a forwarded JWT (config.utils.resolve_jwt_claims)
and, when valid, makes the JWT the source of identity; under RBAC it also
supplies/enforces roles. We monkeypatch ``resolve_jwt_claims`` (no real keys
needed) and ``_attach_db_user_id`` (no DB needed) to isolate the dependency
logic, and drive RBAC on/off via ``OPENRAG_RBAC_ENFORCE``.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import config.utils as config_utils  # noqa: E402
import dependencies as deps  # noqa: E402
from dependencies import _stage_jwt_roles, get_api_key_user_async  # noqa: E402


class _FakeRequest:
    """Minimal stand-in for starlette Request used by the auth dependency."""

    def __init__(self, headers: dict | None = None):
        self.headers = headers or {}
        self.cookies: dict[str, str] = {}
        self.state = SimpleNamespace()


@pytest.fixture(autouse=True)
def _role_claim_env(monkeypatch):
    """Known role-claim mapping for every test."""
    monkeypatch.setenv("OPENRAG_JWT_ROLES_CLAIM", "openrag_roles")
    monkeypatch.setenv("OPENRAG_ROLE_CLAIM_ADMIN", "admin")
    monkeypatch.setenv("OPENRAG_ROLE_CLAIM_DEVELOPER", "manager")
    monkeypatch.setenv("OPENRAG_ROLE_CLAIM_USER", "user")
    monkeypatch.delenv("OPENRAG_ROLE_CLAIM_VIEWER", raising=False)
    # Pin the JWT header name so tests stay decoupled from its default.
    monkeypatch.setenv("OPENRAG_JWT_AUTH_HEADER", "X-OpenRAG-JWT")


# ── _stage_jwt_roles ────────────────────────────────────────────────────


def test_stage_roles_rbac_off_is_noop(monkeypatch):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "false")
    req = _FakeRequest()
    _stage_jwt_roles(req, {"openrag_roles": ["admin"]}, "alice")
    assert req.state.jwt_roles is None


def test_stage_roles_rbac_on_extracts(monkeypatch):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    req = _FakeRequest()
    _stage_jwt_roles(req, {"openrag_roles": ["manager"]}, "alice")
    assert req.state.jwt_roles == ["developer"]


def test_stage_roles_rbac_on_no_role_401(monkeypatch):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    req = _FakeRequest()
    with pytest.raises(HTTPException) as exc:
        _stage_jwt_roles(req, {"sub": "alice"}, "alice")
    assert exc.value.status_code == 401


# ── get_api_key_user_async — JWT header branch ──────────────────────────


@pytest.fixture
def _patch_attach(monkeypatch):
    """Replace _attach_db_user_id with a passthrough that records state."""
    captured = {}

    async def _fake_attach(request, user):
        captured["jwt_roles"] = getattr(request.state, "jwt_roles", "UNSET")
        captured["user"] = user
        return user

    monkeypatch.setattr(deps, "_attach_db_user_id", _fake_attach)
    return captured


def _patch_verify(monkeypatch, claims):
    monkeypatch.setattr(config_utils, "resolve_jwt_claims", lambda *a, **k: claims)


@pytest.mark.asyncio
async def test_valid_jwt_rbac_off_identity_only(monkeypatch, _patch_attach):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "false")
    _patch_verify(monkeypatch, {"sub": "s1", "username": "alice", "display_name": "Alice"})
    req = _FakeRequest({"X-OpenRAG-JWT": "Bearer tok"})

    user = await get_api_key_user_async(req, api_key_service=None, session_manager=None)

    assert user.provider == "ibm_ams"
    assert user.user_id == "alice"
    assert user.name == "Alice"
    assert user.jwt_token == "Bearer tok"
    assert _patch_attach["jwt_roles"] is None  # identity only, no roles


@pytest.mark.asyncio
async def test_valid_jwt_rbac_on_syncs_roles(monkeypatch, _patch_attach):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    _patch_verify(monkeypatch, {"sub": "s1", "username": "alice", "openrag_roles": ["admin"]})
    req = _FakeRequest({"X-OpenRAG-JWT": "tok"})  # raw, no Bearer prefix

    user = await get_api_key_user_async(req, api_key_service=None, session_manager=None)

    assert user.user_id == "alice"
    assert user.jwt_token == "Bearer tok"
    # roles staged BEFORE _attach_db_user_id ran (so the DB sync sees them)
    assert _patch_attach["jwt_roles"] == ["admin"]


@pytest.mark.asyncio
async def test_valid_jwt_rbac_on_no_role_401(monkeypatch, _patch_attach):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    _patch_verify(monkeypatch, {"sub": "s1", "username": "alice"})  # no roles claim
    req = _FakeRequest({"X-OpenRAG-JWT": "tok"})

    with pytest.raises(HTTPException) as exc:
        await get_api_key_user_async(req, api_key_service=None, session_manager=None)
    assert exc.value.status_code == 401
    assert exc.value.detail == "User has no OpenRAG roles assigned"


@pytest.mark.asyncio
async def test_invalid_jwt_rbac_on_401(monkeypatch, _patch_attach):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    _patch_verify(monkeypatch, None)  # verification failed
    req = _FakeRequest({"X-OpenRAG-JWT": "garbage"})

    with pytest.raises(HTTPException) as exc:
        await get_api_key_user_async(req, api_key_service=None, session_manager=None)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid or unverifiable JWT"


@pytest.mark.asyncio
async def test_invalid_jwt_rbac_off_falls_through_to_api_key(monkeypatch):
    """RBAC off + bad JWT -> ignore the JWT and require an API key (terminal 401)."""
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "false")
    monkeypatch.setenv("IBM_AUTH_ENABLED", "false")
    _patch_verify(monkeypatch, None)
    req = _FakeRequest({"X-OpenRAG-JWT": "garbage"})  # no API key header

    with pytest.raises(HTTPException) as exc:
        await get_api_key_user_async(req, api_key_service=None, session_manager=None)
    # Fell through to the API-key path's terminal "API key required".
    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "API key required"


@pytest.mark.asyncio
async def test_no_header_does_not_engage_jwt_path(monkeypatch):
    """No JWT header -> the JWT branch is skipped entirely (regression guard)."""
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    monkeypatch.setenv("IBM_AUTH_ENABLED", "false")

    def _boom(*a, **k):  # must never be called when no header present
        raise AssertionError("resolve_jwt_claims should not run without the header")

    monkeypatch.setattr(config_utils, "resolve_jwt_claims", _boom)
    req = _FakeRequest({})

    with pytest.raises(HTTPException) as exc:
        await get_api_key_user_async(req, api_key_service=None, session_manager=None)
    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "API key required"
