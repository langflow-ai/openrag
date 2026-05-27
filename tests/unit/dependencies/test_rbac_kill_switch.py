"""OPENRAG_RBAC_ENFORCE kill switch.

When the flag is off, every authenticated user passes every gate:
- ``require_permission`` returns the user without checking
- ``RBACService.assert_owner_or_perm`` returns immediately
- API-key role overrides are also bypassed
- ``/users/me`` reports the full permission catalog so the UI shows
  every action

This is the "pre-RBAC behavior" mode the operator can toggle on for
single-user OSS installs or emergency debugging.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.seed import seed_roles_and_permissions  # noqa: E402
from dependencies import (  # noqa: E402
    get_current_user,
    get_db_session,
    get_rbac_service,
)
from services.rbac_service import RBACService, is_rbac_enforced  # noqa: E402
from services.user_service import ensure_user_row  # noqa: E402
from session_manager import User  # noqa: E402

# ----------------------------------------------------------------------
# is_rbac_enforced() resolver
# ----------------------------------------------------------------------


def test_default_does_not_enforce(monkeypatch):
    """RBAC is opt-in: with no env var set, enforcement is off."""
    monkeypatch.delenv("OPENRAG_RBAC_ENFORCE", raising=False)
    assert is_rbac_enforced() is False


@pytest.mark.parametrize("v", ["true", "TRUE", "1", "yes", "on", "True"])
def test_on_values(monkeypatch, v):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", v)
    assert is_rbac_enforced() is True


@pytest.mark.parametrize("v", ["false", "0", "no", "off", "", "garbage"])
def test_off_values(monkeypatch, v):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", v)
    assert is_rbac_enforced() is False


# ----------------------------------------------------------------------
# Bypass — require_permission + assert_owner_or_perm
# ----------------------------------------------------------------------


@pytest_asyncio.fixture
async def app(monkeypatch):
    """Spin up a tiny FastAPI app with one gated endpoint, two personas
    (admin + non-admin), and the kill switch monkeypatch-controlled."""
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    personas: dict[str, User] = {}
    async with SessionLocal() as s:
        await seed_roles_and_permissions(s)
        admin_db = await ensure_user_row(
            s, User(user_id="admin-sub", email="a@x", name="A", provider="google")
        )
        user_db = await ensure_user_row(
            s, User(user_id="user-sub", email="u@x", name="U", provider="google")
        )
        await s.commit()
        personas["admin"] = User(user_id=admin_db.id, email="a@x", name="A", provider="google")
        personas["user"] = User(user_id=user_db.id, email="u@x", name="U", provider="google")

    rbac = RBACService(SessionLocal)
    fastapi_app = FastAPI()

    async def _stub_user(request: Request) -> User:
        persona = request.headers.get("X-Test-Persona", "user")
        return personas[persona]

    async def _db_session():
        async with SessionLocal() as s:
            yield s

    fastapi_app.dependency_overrides[get_current_user] = _stub_user
    fastapi_app.dependency_overrides[get_rbac_service] = lambda: rbac
    fastapi_app.dependency_overrides[get_db_session] = _db_session

    # Mount a minimal endpoint behind a real require_permission gate so the
    # kill switch can be exercised without depending on any specific router.
    from dependencies import require_permission

    @fastapi_app.get("/admin/users")
    async def _gated(_=Depends(require_permission("users:list"))):
        return []

    yield fastapi_app, SessionLocal, rbac, personas
    await engine.dispose()


@pytest.mark.asyncio
async def test_kill_switch_bypasses_require_permission(app, monkeypatch):
    """`user` persona has no admin role but DELETE /admin/users requires
    `users:delete`. Default = 403. With kill switch = 200/4xx-from-handler."""
    fastapi_app, _, _, personas = app

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # Enforced: blocked
        monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
        r = await c.get("/admin/users", headers={"X-Test-Persona": "user"})
        assert r.status_code == 403
        assert r.json()["detail"]["required"] == "users:list"

        # Kill switch off (default): passes
        monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "false")
        r = await c.get("/admin/users", headers={"X-Test-Persona": "user"})
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_kill_switch_bypasses_assert_owner_or_perm(monkeypatch):
    """The shared helper used by `:own` endpoints must also bypass."""
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "false")

    # Mock session_factory — it should never be hit
    factory = MagicMock(side_effect=AssertionError("DB should not be queried"))
    rbac = RBACService(factory)

    # Non-owner, no permissions → would normally 403; kill switch returns silently
    user = User(user_id="alice", email="a@x", name="A", provider="google")
    await rbac.assert_owner_or_perm(
        user=user,
        owner_id="bob",
        owned_perm="kf:delete:own",
        any_perm="kf:delete",
    )


@pytest.mark.asyncio
async def test_kill_switch_bypasses_api_key_role_override(app, monkeypatch):
    """API-key role_override is also bypassed — the flag is unconditional."""
    fastapi_app, _, _, _ = app
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "false")

    # Inject a request middleware that pretends an API key with a
    # "viewer-only" role override is in play. With the kill switch the
    # role_override is never consulted, so the request still succeeds.
    @fastapi_app.middleware("http")
    async def _inject_key_scope(request, call_next):
        request.state.api_key_role_ids = ["nonexistent-role-id"]
        return await call_next(request)

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/admin/users", headers={"X-Test-Persona": "user"})
    assert r.status_code == 200


# ----------------------------------------------------------------------
# /users/me — full catalog when the kill switch is on
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_me_returns_full_permission_catalog_when_disabled(app, monkeypatch):
    fastapi_app, SessionLocal, _, _ = app
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "false")

    from api import users as users_api

    fastapi_app.include_router(users_api.router)

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/users/me", headers={"X-Test-Persona": "user"})
    assert r.status_code == 200
    body = r.json()

    # Should include the entire seeded catalog
    expected_subset = {"users:list", "users:delete", "config:write", "chat:use"}
    assert expected_subset.issubset(set(body["permissions"]))
    # And the flag is surfaced so the UI can hide RBAC-only sections
    assert body["rbac_enforced"] is False


@pytest.mark.asyncio
async def test_me_returns_only_user_perms_when_enforced(app, monkeypatch):
    fastapi_app, _, _, _ = app
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")

    from api import users as users_api

    fastapi_app.include_router(users_api.router)

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/users/me", headers={"X-Test-Persona": "user"})
    assert r.status_code == 200
    body = r.json()

    # Should NOT include admin-only perms when enforced
    assert "users:delete" not in body["permissions"]
    assert body["rbac_enforced"] is True
