"""Phase 3: admin RBAC endpoints — happy paths + access control."""

import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.repositories import RoleRepo  # noqa: E402
from db.seed import seed_roles_and_permissions  # noqa: E402
from dependencies import (  # noqa: E402
    get_current_user,
    get_db_session,
    get_rbac_service,
)
from services.rbac_service import RBACService  # noqa: E402
from services.user_service import ensure_user_row  # noqa: E402
from session_manager import User  # noqa: E402

PERSONAS: dict[str, User] = {}


@pytest_asyncio.fixture
async def app(monkeypatch):
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    PERSONAS.clear()
    async with SessionLocal() as s:
        await seed_roles_and_permissions(s)
        admin_db = await ensure_user_row(
            s, User(user_id="admin-sub", email="a@x.com", name="A", provider="google")
        )
        user_db = await ensure_user_row(
            s, User(user_id="user-sub", email="u@x.com", name="U", provider="google")
        )
        await s.commit()

        PERSONAS["admin"] = User(
            user_id=admin_db.id, email="a@x.com", name="A", provider="google"
        )
        PERSONAS["user"] = User(
            user_id=user_db.id, email="u@x.com", name="U", provider="google"
        )

    rbac = RBACService(SessionLocal)

    fastapi_app = FastAPI()

    async def _stub_user(request: Request) -> User:
        persona = request.headers.get("X-Test-Persona", "admin")
        return PERSONAS[persona]

    async def _db_session():
        async with SessionLocal() as s:
            yield s

    fastapi_app.dependency_overrides[get_current_user] = _stub_user
    fastapi_app.dependency_overrides[get_rbac_service] = lambda: rbac
    fastapi_app.dependency_overrides[get_db_session] = _db_session

    from api.admin import rbac as admin_rbac
    fastapi_app.include_router(admin_rbac.router)

    yield fastapi_app, SessionLocal, rbac
    await engine.dispose()


def _admin_headers():
    return {"X-Test-Persona": "admin"}


def _user_headers():
    return {"X-Test-Persona": "user"}


@pytest.mark.asyncio
async def test_admin_can_list_users(app):
    fastapi_app, _, _ = app
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/admin/users", headers=_admin_headers())
    assert r.status_code == 200
    assert len(r.json()) == 2


@pytest.mark.asyncio
async def test_non_admin_cannot_list_users(app):
    fastapi_app, _, _ = app
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/admin/users", headers=_user_headers())
    assert r.status_code == 403
    assert r.json()["detail"]["required"] == "users:list"


@pytest.mark.asyncio
async def test_admin_can_promote_user(app):
    fastapi_app, SessionLocal, rbac = app
    user_id = PERSONAS["user"].user_id

    async with SessionLocal() as s:
        dev_role = await RoleRepo(s).get_by_name("developer")
    role_id = dev_role.id

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            f"/admin/users/{user_id}/roles",
            json={"role_id": role_id},
            headers=_admin_headers(),
        )
    assert r.status_code == 200
    body = r.json()
    assert "developer" in body["roles"]


@pytest.mark.asyncio
async def test_cannot_remove_last_admin(app):
    fastapi_app, SessionLocal, _ = app
    admin_id = PERSONAS["admin"].user_id

    async with SessionLocal() as s:
        admin_role = await RoleRepo(s).get_by_name("admin")

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.delete(
            f"/admin/users/{admin_id}/roles/{admin_role.id}",
            headers=_admin_headers(),
        )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "cannot_remove_last_admin"


@pytest.mark.asyncio
async def test_admin_can_create_and_delete_custom_role(app):
    fastapi_app, _, _ = app
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # Create
        r = await c.post(
            "/admin/roles",
            json={
                "name": "reviewer",
                "description": "Doc reviewer",
                "permissions": ["chat:use", "search:use", "kf:edit:own"],
            },
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        role = r.json()
        assert role["name"] == "reviewer"
        assert role["is_system"] is False
        assert set(role["permissions"]) == {"chat:use", "search:use", "kf:edit:own"}

        # List
        r = await c.get("/admin/roles", headers=_admin_headers())
        names = {row["name"] for row in r.json()}
        assert "reviewer" in names

        # Delete
        r = await c.delete(f"/admin/roles/{role['id']}", headers=_admin_headers())
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_cannot_delete_system_role(app):
    fastapi_app, SessionLocal, _ = app
    async with SessionLocal() as s:
        admin_role = await RoleRepo(s).get_by_name("admin")

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.delete(
            f"/admin/roles/{admin_role.id}", headers=_admin_headers()
        )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "cannot_delete_system_role"


@pytest.mark.asyncio
async def test_role_edit_replaces_permissions_and_invalidates_cache(app):
    fastapi_app, SessionLocal, rbac = app
    async with SessionLocal() as s:
        user_role = await RoleRepo(s).get_by_name("user")
    user_id = PERSONAS["user"].user_id

    # Warm cache
    perms_before = await rbac.get_user_permissions(user_id)
    assert "chat:use" in perms_before

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.patch(
            f"/admin/roles/{user_role.id}",
            json={"permissions": ["search:use"]},
            headers=_admin_headers(),
        )
    assert r.status_code == 200

    perms_after = await rbac.get_user_permissions(user_id)
    assert "chat:use" not in perms_after
    assert "search:use" in perms_after


@pytest.mark.asyncio
async def test_audit_log_records_role_assignment(app):
    fastapi_app, SessionLocal, _ = app
    user_id = PERSONAS["user"].user_id
    async with SessionLocal() as s:
        dev_role = await RoleRepo(s).get_by_name("developer")

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post(
            f"/admin/users/{user_id}/roles",
            json={"role_id": dev_role.id},
            headers=_admin_headers(),
        )

        r = await c.get("/admin/audit?limit=50", headers=_admin_headers())
    assert r.status_code == 200
    events = [row["event"] for row in r.json()]
    assert "user.role.assigned" in events


@pytest.mark.asyncio
async def test_permissions_endpoint(app):
    fastapi_app, _, _ = app
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/admin/permissions", headers=_admin_headers())
    assert r.status_code == 200
    names = {p["name"] for p in r.json()}
    # Sample known catalog members
    assert {"config:write", "users:list", "chat:use", "kf:create"}.issubset(names)


@pytest.mark.asyncio
async def test_cannot_delete_self(app):
    fastapi_app, _, _ = app
    admin_id = PERSONAS["admin"].user_id
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.delete(f"/admin/users/{admin_id}", headers=_admin_headers())
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "cannot_delete_self"


@pytest.mark.asyncio
async def test_cannot_delete_last_admin(app):
    """Single-admin DB. A non-admin actor with `users:delete` permission
    tries to DELETE the sole admin → cannot_delete_last_admin (400).

    The cannot_delete_self guard runs first, so we use a non-admin actor
    with a custom role granting `users:delete`. This isolates the
    last-admin guard from the self-delete guard.
    """
    fastapi_app, SessionLocal, _ = app
    admin_id = PERSONAS["admin"].user_id
    user_id = PERSONAS["user"].user_id

    # Grant the `user` persona a custom role that includes users:delete
    # without being an admin. This requires us to create the role and
    # assign it via the admin endpoints.
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/admin/roles",
            json={"name": "user_deleter", "permissions": ["users:delete"]},
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        deleter_role_id = r.json()["id"]
        r = await c.post(
            f"/admin/users/{user_id}/roles",
            json={"role_id": deleter_role_id},
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        # `user` (non-admin, has users:delete) tries to delete the sole admin.
        r = await c.delete(
            f"/admin/users/{admin_id}",
            headers={"X-Test-Persona": "user"},
        )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "cannot_delete_last_admin"


@pytest.mark.asyncio
async def test_can_delete_non_last_admin(app):
    """Two-admin DB → deleting one admin leaves the other; should succeed."""
    fastapi_app, SessionLocal, _ = app
    user_id = PERSONAS["user"].user_id
    async with SessionLocal() as s:
        admin_role = await RoleRepo(s).get_by_name("admin")

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # Promote user to admin → now 2 admins.
        r = await c.post(
            f"/admin/users/{user_id}/roles",
            json={"role_id": admin_role.id},
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        # Admin (still admin) deletes the second admin → succeeds.
        r = await c.delete(
            f"/admin/users/{user_id}",
            headers=_admin_headers(),
        )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_cannot_deactivate_last_admin(app):
    """PATCH /users/{admin_id} {is_active: False} on the only admin → 400."""
    fastapi_app, SessionLocal, _ = app
    admin_id = PERSONAS["admin"].user_id
    async with SessionLocal() as s:
        admin_role = await RoleRepo(s).get_by_name("admin")

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.patch(
            f"/admin/users/{admin_id}",
            json={"is_active": False},
            headers=_admin_headers(),
        )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "cannot_deactivate_last_admin"


@pytest.mark.asyncio
async def test_unknown_permission_rejected_on_create_role(app):
    fastapi_app, _, _ = app
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/admin/roles",
            json={"name": "weird", "permissions": ["does:not:exist"]},
            headers=_admin_headers(),
        )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "unknown_permission"
