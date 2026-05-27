"""Phase 2: end-to-end gate test for require_permission.

Builds a tiny FastAPI app whose routes use the real `require_permission`
dependency against an in-memory SQLite seeded with the real catalog. The
in-process auth dependency is overridden via FastAPI's dependency_overrides
so we can switch between admin / developer / user / viewer personas per
request without touching cookies or JWTs.
"""

import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.models import User as UserRow  # noqa: E402
from db.repositories import RoleRepo  # noqa: E402
from db.seed import seed_roles_and_permissions  # noqa: E402
from dependencies import (  # noqa: E402
    _ENSURED_USER_IDS,
    _user_cache_key,
    get_current_user,
    get_rbac_service,
    require_all_permissions,
    require_permission,
)
from services.rbac_service import RBACService  # noqa: E402
from services.user_service import ensure_user_row  # noqa: E402
from session_manager import User  # noqa: E402

# Map role-name -> User dataclass we hand to overrides
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
        # Every user gets OPENRAG_DEFAULT_ROLE = "user"; promote personas
        # explicitly (no bootstrap-admin rule).
        admin_db = await ensure_user_row(
            s, User(user_id="admin-sub", email="a@x.com", name="A", provider="google")
        )
        user_db = await ensure_user_row(
            s, User(user_id="user-sub", email="u@x.com", name="U", provider="google")
        )

        # Promote a fresh user to "developer" by replacing its default role.
        dev_db = await ensure_user_row(
            s, User(user_id="dev-sub", email="d@x.com", name="D", provider="google")
        )
        role_repo = RoleRepo(s)
        user_role = await role_repo.get_by_name("user")
        admin_role = await role_repo.get_by_name("admin")
        dev_role = await role_repo.get_by_name("developer")
        viewer_role = await role_repo.get_by_name("viewer")
        # Promote the admin persona from its default "user" role to "admin".
        await role_repo.revoke_role(admin_db.id, user_role.id)
        await role_repo.assign_role(admin_db.id, admin_role.id)
        await role_repo.revoke_role(dev_db.id, user_role.id)
        await role_repo.assign_role(dev_db.id, dev_role.id)

        # And a viewer
        viewer_db = await ensure_user_row(
            s, User(user_id="viewer-sub", email="v@x.com", name="V", provider="google")
        )
        await role_repo.revoke_role(viewer_db.id, user_role.id)
        await role_repo.assign_role(viewer_db.id, viewer_role.id)

        aliased_db = UserRow(
            id="db-aliased-user",
            oauth_provider="google",
            oauth_subject="oauth-aliased-sub",
            email="alias@x.com",
            display_name="Alias",
        )
        s.add(aliased_db)
        await s.flush()
        await role_repo.assign_role(aliased_db.id, user_role.id)

        await s.commit()

        # Map persona name -> User dataclass with id matching the DB row id so
        # require_permission's lookups via rbac.get_user_permissions(user.user_id)
        # resolve correctly. Note: User.user_id is the *DB id* here so the key
        # lookups (which use db_user.id) line up.
        PERSONAS["admin"] = User(user_id=admin_db.id, email="a@x.com", name="A", provider="google")
        PERSONAS["user"] = User(user_id=user_db.id, email="u@x.com", name="U", provider="google")
        PERSONAS["developer"] = User(
            user_id=dev_db.id, email="d@x.com", name="D", provider="google"
        )
        PERSONAS["viewer"] = User(
            user_id=viewer_db.id, email="v@x.com", name="V", provider="google"
        )
        PERSONAS["aliased"] = User(
            user_id="oauth-aliased-sub",
            email="alias@x.com",
            name="Alias",
            provider="google",
        )
        _ENSURED_USER_IDS[_user_cache_key(PERSONAS["aliased"])] = aliased_db.id

    rbac = RBACService(SessionLocal)

    app = FastAPI()

    async def _stub_user(request: Request) -> User:
        persona = request.headers.get("X-Test-Persona", "user")
        return PERSONAS[persona]

    app.dependency_overrides[get_current_user] = _stub_user
    app.dependency_overrides[get_rbac_service] = lambda: rbac

    @app.post("/test/config-write")
    async def write_config(user=Depends(require_permission("config:write"))):
        return JSONResponse({"user_id": user.user_id})

    @app.post("/test/chat-use")
    async def use_chat(user=Depends(require_permission("chat:use"))):
        return JSONResponse({"user_id": user.user_id})

    @app.post("/test/kf-create")
    async def kf_create(user=Depends(require_permission("kf:create"))):
        return JSONResponse({"user_id": user.user_id})

    @app.post("/test/users-list")
    async def users_list(user=Depends(require_permission("users:list"))):
        return JSONResponse({"user_id": user.user_id})

    @app.post("/test/flows-edit")
    async def flows_edit(user=Depends(require_permission("flows:edit"))):
        return JSONResponse({"user_id": user.user_id})

    @app.post("/test/upload-context")
    async def upload_context_gate(
        user=Depends(require_all_permissions(("knowledge:upload", "chat:use"))),
    ):
        return JSONResponse({"user_id": user.user_id})

    @app.post("/test/whoami")
    async def whoami(user=Depends(require_permission("chat:use"))):
        return JSONResponse({"user_id": user.user_id, "db_user_id": user.db_user_id})

    yield app
    _ENSURED_USER_IDS.pop(_user_cache_key(PERSONAS["aliased"]), None)
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "persona, perm_path, expected",
    [
        # admin → everything passes
        ("admin", "/test/config-write", 200),
        ("admin", "/test/chat-use", 200),
        ("admin", "/test/kf-create", 200),
        ("admin", "/test/users-list", 200),
        ("admin", "/test/flows-edit", 200),
        # developer → no infra writes, no users:list
        ("developer", "/test/config-write", 403),
        ("developer", "/test/chat-use", 200),
        ("developer", "/test/kf-create", 200),
        ("developer", "/test/users-list", 403),
        ("developer", "/test/flows-edit", 200),
        # default user → chat + kf:create yes; flows:edit no
        ("user", "/test/config-write", 403),
        ("user", "/test/chat-use", 200),
        ("user", "/test/kf-create", 200),
        ("user", "/test/users-list", 403),
        ("user", "/test/flows-edit", 403),
        # viewer → chat yes; everything else no
        ("viewer", "/test/config-write", 403),
        ("viewer", "/test/chat-use", 200),
        ("viewer", "/test/kf-create", 403),
        ("viewer", "/test/users-list", 403),
        ("viewer", "/test/flows-edit", 403),
        # upload-context is both ingestion and chat behavior
        ("user", "/test/upload-context", 200),
        ("viewer", "/test/upload-context", 403),
    ],
)
async def test_permission_enforcement(app, persona, perm_path, expected):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(perm_path, headers={"X-Test-Persona": persona})
    assert r.status_code == expected, f"{persona} {perm_path} -> {r.status_code} {r.text}"
    if expected == 403:
        body = r.json()
        assert body["detail"]["error"] == "permission_denied"


@pytest.mark.asyncio
async def test_403_response_includes_required_perm(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/test/config-write", headers={"X-Test-Persona": "user"})
    assert r.status_code == 403
    assert r.json()["detail"]["required"] == "config:write"


@pytest.mark.asyncio
async def test_all_permissions_response_lists_required_permissions(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/test/upload-context", headers={"X-Test-Persona": "viewer"})
    assert r.status_code == 403
    assert r.json()["detail"]["required"] == ["knowledge:upload", "chat:use"]


@pytest.mark.asyncio
async def test_permission_check_uses_resolved_db_user_id(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/test/whoami", headers={"X-Test-Persona": "aliased"})
    assert r.status_code == 200
    assert r.json() == {
        "user_id": "oauth-aliased-sub",
        "db_user_id": "db-aliased-user",
    }
