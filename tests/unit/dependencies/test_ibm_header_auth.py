"""IBM AMS auth: JWT source switches from cookie to header under RBAC.

Covers the RBAC-gated token source in ``_get_ibm_user`` (``src/dependencies.py``):
when JWT-role sync is enabled the end-user JWT is read from the gateway-forwarded
header named by ``get_jwt_auth_header()``; when RBAC is off the existing
``ibm-openrag-session`` cookie flow is preserved. ``decode_ibm_jwt`` is
monkeypatched so no real token is needed.
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

import auth.ibm_auth as ibm_auth  # noqa: E402
import config.settings as app_settings  # noqa: E402
from dependencies import _get_ibm_user  # noqa: E402

COOKIE_NAME = "ibm-openrag-session"


class _FakeRequest:
    """Minimal stand-in for starlette Request used by ``_get_ibm_user``."""

    def __init__(self, headers: dict | None = None, cookies: dict | None = None):
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.state = SimpleNamespace()
        # Empty services -> the connector lookup in Option 1 no-ops.
        self.app = SimpleNamespace(state=SimpleNamespace(services={}))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OPENRAG_JWT_ROLES_CLAIM", "openrag_roles")
    monkeypatch.setenv("OPENRAG_ROLE_CLAIM_ADMIN", "admin")
    monkeypatch.setenv("OPENRAG_ROLE_CLAIM_DEVELOPER", "manager")
    monkeypatch.setenv("OPENRAG_ROLE_CLAIM_USER", "user")
    monkeypatch.delenv("OPENRAG_ROLE_CLAIM_VIEWER", raising=False)
    monkeypatch.setenv("OPENRAG_JWT_AUTH_HEADER", "X-OpenRAG-JWT")
    # Keep the Option -1 env override from short-circuiting the function.
    monkeypatch.setattr(app_settings, "PLATFORM_USERNAME", None)
    monkeypatch.setattr(app_settings, "PLATFORM_PASSWORD", None)


@pytest.mark.asyncio
async def test_rbac_on_reads_jwt_from_header(monkeypatch):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    claims = {"sub": "s1", "username": "alice", "display_name": "Alice", "openrag_roles": ["admin"]}
    monkeypatch.setattr(ibm_auth, "decode_ibm_jwt", lambda tok: claims if tok == "tok" else None)
    # Cookie present too — it must be ignored when RBAC is on.
    req = _FakeRequest(headers={"X-OpenRAG-JWT": "Bearer tok"}, cookies={COOKIE_NAME: "COOKIE"})

    user = await _get_ibm_user(req, required=True)

    assert user is not None
    assert user.user_id == "alice"
    assert user.name == "Alice"
    assert user.jwt_token == "Bearer tok"  # built from the header token, not the cookie
    assert req.state.jwt_roles == ["admin"]


@pytest.mark.asyncio
async def test_rbac_off_reads_jwt_from_cookie(monkeypatch):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "false")
    claims = {"sub": "s2", "username": "bob"}
    monkeypatch.setattr(ibm_auth, "decode_ibm_jwt", lambda tok: claims if tok == "ctok" else None)
    # Header present too — it must be ignored when RBAC is off.
    req = _FakeRequest(headers={"X-OpenRAG-JWT": "Bearer HEADERTOK"}, cookies={COOKIE_NAME: "ctok"})

    user = await _get_ibm_user(req, required=True)

    assert user is not None
    assert user.user_id == "bob"
    assert user.jwt_token == "Bearer ctok"
    assert req.state.jwt_roles is None  # legacy default-role path under RBAC off


@pytest.mark.asyncio
async def test_rbac_on_missing_header_401(monkeypatch):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")

    def _boom(tok):  # decode must not run when no header token is present
        raise AssertionError("decode_ibm_jwt should not be called without a header token")

    monkeypatch.setattr(ibm_auth, "decode_ibm_jwt", _boom)
    # Cookie present but ignored under RBAC -> no token -> unauthenticated.
    req = _FakeRequest(headers={}, cookies={COOKIE_NAME: "ctok"})

    with pytest.raises(HTTPException) as exc:
        await _get_ibm_user(req, required=True)
    assert exc.value.status_code == 401
