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

import base64  # noqa: E402

import auth.request_identity as deps  # noqa: E402
import config.settings as app_settings  # noqa: E402
import config.utils as config_utils  # noqa: E402
from auth.request_identity import (  # noqa: E402
    _stage_jwt_roles,
)
from auth.request_identity import (  # noqa: E402
    resolve_api_key_user as get_api_key_user_async,
)


class _FakeRequest:
    """Minimal stand-in for starlette Request used by the auth dependency."""

    def __init__(self, headers: dict | None = None, services: dict | None = None):
        self.headers = headers or {}
        self.cookies: dict[str, str] = {}
        self.state = SimpleNamespace()
        if services is not None:
            self.app = SimpleNamespace(state=SimpleNamespace(services=services))


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
    """Replace _attach_request_user with a passthrough that records state."""
    captured = {}

    async def _fake_attach(request, user, session_manager, token_hint=None):
        captured["jwt_roles"] = getattr(request.state, "jwt_roles", "UNSET")
        captured["user"] = user
        return user

    monkeypatch.setattr(deps, "_attach_request_user", _fake_attach)
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
    # 401 fires inside _stage_jwt_roles, before _attach_request_user -> no DB
    # user/role write, so a roles-less JWT can never reach _sync_jwt_roles.
    assert "user" not in _patch_attach


@pytest.mark.asyncio
async def test_invalid_jwt_rbac_on_401(monkeypatch, _patch_attach):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    _patch_verify(monkeypatch, None)  # verification failed
    req = _FakeRequest({"X-OpenRAG-JWT": "garbage"})

    with pytest.raises(HTTPException) as exc:
        await get_api_key_user_async(req, api_key_service=None, session_manager=None)
    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "invalid_jwt"
    assert "could not be verified" in exc.value.detail["message"]


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


# ── get_api_key_user_async — lakehouse credential resolution (IBM auth) ─
#
# In SaaS, Traefik authenticates X-Username/X-Api-Key and injects the JWT.
# When the JWT is present it is primary for ALL operations (identity, roles,
# OpenSearch via OIDC) — credential resolution is skipped entirely. Only when
# the JWT is absent do lakehouse Basic credentials (credentials header)
# become the jwt_token, mirroring _get_ibm_user's header branch.

_B64 = base64.b64encode(b"alice:secret").decode()
_CLAIMS = {"sub": "s1", "username": "alice", "openrag_roles": ["admin"]}


class _FakeConnectionManager:
    def __init__(self, stored_credentials: str | None = None, broken: bool = False):
        self.stored_credentials = stored_credentials
        self.broken = broken
        self.upserts: list[dict] = []

    async def upsert_ibm_credentials(self, user_id, basic_credentials, username):
        if self.broken:
            raise RuntimeError("connections store unavailable")
        self.upserts.append(
            {"user_id": user_id, "basic_credentials": basic_credentials, "username": username}
        )

    async def list_connections(self, user_id, connector_type):
        if self.broken:
            raise RuntimeError("connections store unavailable")
        if self.stored_credentials is None:
            return []
        return [SimpleNamespace(config={"basic_credentials": self.stored_credentials})]


def _ibm_setup(monkeypatch, stored_credentials=None, broken=False):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    monkeypatch.setattr(app_settings, "IBM_AUTH_ENABLED", True)
    _patch_verify(monkeypatch, dict(_CLAIMS))
    manager = _FakeConnectionManager(stored_credentials, broken=broken)
    services = {"connector_service": SimpleNamespace(connection_manager=manager)}
    return manager, services


@pytest.mark.asyncio
async def test_jwt_present_keeps_bearer_and_skips_credential_resolution(monkeypatch, _patch_attach):
    """JWT present -> it is primary for everything; the credentials header is
    ignored and nothing is persisted."""
    manager, services = _ibm_setup(monkeypatch)
    req = _FakeRequest(
        {"X-OpenRAG-JWT": "Bearer tok", "X-IBM-LH-Credentials": _B64},
        services=services,
    )

    user = await get_api_key_user_async(req, api_key_service=None, session_manager=None)

    assert user.user_id == "alice"  # identity stays JWT-derived
    assert user.jwt_token == "Bearer tok"
    assert user.opensearch_username is None
    assert user.opensearch_credentials is None
    assert manager.upserts == []


@pytest.mark.asyncio
async def test_jwt_present_never_queries_connections_store(monkeypatch, _patch_attach):
    """A broken connections store cannot affect a JWT-authenticated request
    because the store is never consulted when the JWT is present."""
    _, services = _ibm_setup(monkeypatch, stored_credentials=_B64, broken=True)
    req = _FakeRequest({"X-OpenRAG-JWT": "Bearer tok"}, services=services)

    user = await get_api_key_user_async(req, api_key_service=None, session_manager=None)

    assert user.jwt_token == "Bearer tok"
    assert user.opensearch_credentials is None


@pytest.mark.asyncio
async def test_jwt_without_credentials_keeps_bearer(monkeypatch, _patch_attach):
    """No lakehouse creds anywhere -> the JWT is the token (primary path)."""
    _, services = _ibm_setup(monkeypatch)
    req = _FakeRequest({"X-OpenRAG-JWT": "Bearer tok"}, services=services)

    user = await get_api_key_user_async(req, api_key_service=None, session_manager=None)

    assert user.jwt_token == "Bearer tok"
    assert user.opensearch_credentials is None


@pytest.mark.asyncio
async def test_no_jwt_uses_lh_credentials_as_token(monkeypatch, _patch_attach):
    """No JWT -> lakehouse credentials from the header become the Basic
    jwt_token and the identity, mirroring _get_ibm_user's header branch."""
    manager, services = _ibm_setup(monkeypatch)
    req = _FakeRequest({"X-IBM-LH-Credentials": _B64}, services=services)

    user = await get_api_key_user_async(req, api_key_service=None, session_manager=None)

    assert user.user_id == "alice"  # from the decoded credentials
    assert user.jwt_token == f"Basic {_B64}"
    assert user.opensearch_username == "alice"
    assert user.opensearch_credentials == _B64
    assert manager.upserts == [{"user_id": "alice", "basic_credentials": _B64, "username": "alice"}]


@pytest.mark.asyncio
async def test_no_jwt_broken_store_still_returns_header_credentials(monkeypatch, _patch_attach):
    """A connections-store failure must not 500 the request: header credentials
    are still used even when persisting them fails."""
    _, services = _ibm_setup(monkeypatch, broken=True)
    req = _FakeRequest({"X-IBM-LH-Credentials": _B64}, services=services)

    user = await get_api_key_user_async(req, api_key_service=None, session_manager=None)

    assert user.jwt_token == f"Basic {_B64}"
    assert user.opensearch_credentials == _B64


@pytest.mark.asyncio
async def test_no_jwt_saas_rbac_on_fails_loud_no_db_write(monkeypatch, _patch_attach):
    """saas + RBAC + no gateway JWT -> fail loud with 401 missing_user_jwt and
    do NOT silently fall back to lakehouse creds (no DB user/role write).

    A roles-less / wrong-identity LH fallback here is what corrupted the shared
    users row the same person sees on UI login; under saas_rbac we must 401
    before any _attach_request_user instead.
    """
    manager, services = _ibm_setup(monkeypatch)
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    errors: list[str] = []
    monkeypatch.setattr(deps.logger, "error", lambda msg, **kw: errors.append(msg))
    # Even with a valid LH-credentials header present, saas_rbac must not use it.
    req = _FakeRequest({"X-IBM-LH-Credentials": _B64}, services=services)

    with pytest.raises(HTTPException) as exc:
        await get_api_key_user_async(req, api_key_service=None, session_manager=None)

    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "missing_user_jwt"
    assert any("JWT not found" in m for m in errors)
    # No DB side effects: _attach_request_user was never reached, and the
    # LH-credentials store was never written.
    assert "user" not in _patch_attach
    assert manager.upserts == []


@pytest.mark.asyncio
async def test_no_jwt_saas_rbac_on_rejects_api_key_fail_fast(monkeypatch, _patch_attach):
    """saas + RBAC + no gateway JWT -> fail fast even when a valid orag_ API key
    is present. In SaaS the gateway JWT is mandatory; the API key must not be
    consulted, and the key service must never be called (no DB side effects)."""
    _ibm_setup(monkeypatch)
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")

    calls: list[str] = []

    class _KeySvc:
        async def validate_key(self, key):
            calls.append(key)
            return {"user_id": "svc-user", "user_email": "svc@example.com", "key_id": "k1"}

    req = _FakeRequest({"X-API-Key": "orag_live_key"})

    with pytest.raises(HTTPException) as exc:
        await get_api_key_user_async(req, api_key_service=_KeySvc(), session_manager=None)

    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "missing_user_jwt"
    assert calls == []  # API key never validated under saas_rbac
    assert "user" not in _patch_attach  # no _attach_request_user / DB write


@pytest.mark.asyncio
async def test_no_jwt_saas_rbac_off_no_error_log(monkeypatch):
    """saas + RBAC off + no JWT -> no error log (legacy API-key behavior)."""
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "false")
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setattr(app_settings, "IBM_AUTH_ENABLED", False)
    errors: list[str] = []
    monkeypatch.setattr(deps.logger, "error", lambda msg, **kw: errors.append(msg))
    req = _FakeRequest({})

    with pytest.raises(HTTPException) as exc:
        await get_api_key_user_async(req, api_key_service=None, session_manager=None)
    assert exc.value.status_code == 401  # API key required
    assert errors == []


# --- on_prem mirrors: on-prem must behave exactly like saas here -----------


@pytest.mark.asyncio
async def test_no_jwt_on_prem_rbac_on_fails_loud_no_db_write(monkeypatch, _patch_attach):
    """on_prem + RBAC + no gateway JWT -> fail loud with 401 missing_user_jwt
    and do NOT silently fall back to lakehouse creds (matches saas)."""
    manager, services = _ibm_setup(monkeypatch)
    monkeypatch.setenv("OPENRAG_RUN_MODE", "on_prem")
    errors: list[str] = []
    monkeypatch.setattr(deps.logger, "error", lambda msg, **kw: errors.append(msg))
    # Even with a valid LH-credentials header present, platform_rbac must not use it.
    req = _FakeRequest({"X-IBM-LH-Credentials": _B64}, services=services)

    with pytest.raises(HTTPException) as exc:
        await get_api_key_user_async(req, api_key_service=None, session_manager=None)

    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "missing_user_jwt"
    assert any("JWT not found" in m for m in errors)
    assert "user" not in _patch_attach
    assert manager.upserts == []


@pytest.mark.asyncio
async def test_no_jwt_on_prem_rbac_on_rejects_api_key_fail_fast(monkeypatch, _patch_attach):
    """on_prem + RBAC + no gateway JWT -> fail fast even when a valid orag_ API
    key is present (matches saas)."""
    _ibm_setup(monkeypatch)
    monkeypatch.setenv("OPENRAG_RUN_MODE", "on_prem")

    calls: list[str] = []

    class _KeySvc:
        async def validate_key(self, key):
            calls.append(key)
            return {"user_id": "svc-user", "user_email": "svc@example.com", "key_id": "k1"}

    req = _FakeRequest({"X-API-Key": "orag_live_key"})

    with pytest.raises(HTTPException) as exc:
        await get_api_key_user_async(req, api_key_service=_KeySvc(), session_manager=None)

    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "missing_user_jwt"
    assert calls == []  # API key never validated under platform_rbac
    assert "user" not in _patch_attach  # no _attach_request_user / DB write


@pytest.mark.asyncio
async def test_no_jwt_on_prem_rbac_off_no_error_log(monkeypatch):
    """on_prem + RBAC off + no JWT -> no error log (legacy API-key behavior),
    exactly as when RBAC is off today."""
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "false")
    monkeypatch.setenv("OPENRAG_RUN_MODE", "on_prem")
    monkeypatch.setattr(app_settings, "IBM_AUTH_ENABLED", False)
    errors: list[str] = []
    monkeypatch.setattr(deps.logger, "error", lambda msg, **kw: errors.append(msg))
    req = _FakeRequest({})

    with pytest.raises(HTTPException) as exc:
        await get_api_key_user_async(req, api_key_service=None, session_manager=None)
    assert exc.value.status_code == 401  # API key required
    assert errors == []


@pytest.mark.asyncio
async def test_invalid_jwt_rbac_on_logs_error(monkeypatch, _patch_attach):
    """Header present but unverifiable under RBAC -> 401 plus a clear
    'failed verification' error log (distinct from the not-found case)."""
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    _patch_verify(monkeypatch, None)
    errors: list[str] = []
    monkeypatch.setattr(deps.logger, "error", lambda msg, **kw: errors.append(msg))
    req = _FakeRequest({"X-OpenRAG-JWT": "garbage"})

    with pytest.raises(HTTPException) as exc:
        await get_api_key_user_async(req, api_key_service=None, session_manager=None)
    assert exc.value.status_code == 401
    assert any("failed verification" in m for m in errors)


@pytest.mark.asyncio
async def test_x_username_headers_never_become_credentials(monkeypatch, _patch_attach):
    """X-Username/X-Api-Key are Traefik's login concern — when the JWT is
    present the backend must not build OpenSearch credentials from them."""
    _, services = _ibm_setup(monkeypatch)
    req = _FakeRequest(
        {
            "X-OpenRAG-JWT": "Bearer tok",
            "X-Username": "alice",
            "X-Api-Key": "lakehouse-api-key",
        },
        services=services,
    )

    user = await get_api_key_user_async(req, api_key_service=None, session_manager=None)

    assert user.user_id == "alice"
    assert user.jwt_token == "Bearer tok"  # not a Basic token minted from X-*
    assert user.opensearch_credentials is None
