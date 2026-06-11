"""require_api_key_permission — RBAC gate for the /v1 (API-key / forwarded-JWT)
surface.

Mirrors require_permission but resolves identity via get_api_key_user_async.
Same kill-switch bypass and 403 detail shape. We seed an in-memory catalog,
build admin/user/viewer personas, override get_api_key_user_async +
get_rbac_service, and drive a probe route plus one real /v1 handler to prove the
gate is wired end-to-end.
"""

import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from api.v1.documents import delete_document_endpoint  # noqa: E402
from api.v1.knowledge_filters import search_endpoint as kf_search_endpoint  # noqa: E402
from db.models import Permission, Role, RolePermission  # noqa: E402
from db.repositories import RoleRepo  # noqa: E402
from db.seed import seed_roles_and_permissions  # noqa: E402
from dependencies import (  # noqa: E402
    get_api_key_user_async,
    get_knowledge_filter_service,
    get_rbac_service,
    get_session_manager,
    require_api_key_any_permission,
    require_api_key_permission,
)
from services.rbac_service import RBACService  # noqa: E402
from services.user_service import ensure_user_row  # noqa: E402
from session_manager import User  # noqa: E402

require_api_key_delete_permission = require_api_key_any_permission(
    ("knowledge:delete:anonymous", "users:delete")
)


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

    personas: dict[str, User] = {}
    async with SessionLocal() as s:
        await seed_roles_and_permissions(s)
        role_repo = RoleRepo(s)
        user_role = await role_repo.get_by_name("user")

        async def _persona(uid: str, role_name: str) -> User:
            row = await ensure_user_row(
                s, User(user_id=uid, email=f"{uid}@x", name=uid, provider="ibm_ams")
            )
            if role_name != "user":  # default role is already "user"
                await role_repo.revoke_role(row.id, user_role.id)
                await role_repo.assign_role(row.id, (await role_repo.get_by_name(role_name)).id)
            return User(user_id=row.id, email=f"{uid}@x", name=uid, provider="ibm_ams")

        personas["admin"] = await _persona("admin-sub", "admin")
        personas["user"] = await _persona("user-sub", "user")
        personas["viewer"] = await _persona("viewer-sub", "viewer")

        # A user with no roles at all — every gated route must 403.
        norole_row = await ensure_user_row(
            s, User(user_id="norole-sub", email="norole@x", name="norole", provider="ibm_ams")
        )
        await role_repo.revoke_role(norole_row.id, user_role.id)
        personas["norole"] = User(
            user_id=norole_row.id, email="norole@x", name="norole", provider="ibm_ams"
        )

        delete_any_row = await ensure_user_row(
            s,
            User(
                user_id="delete-any-sub",
                email="delete-any@x",
                name="delete-any",
                provider="ibm_ams",
            ),
        )
        await role_repo.revoke_role(delete_any_row.id, user_role.id)
        delete_any_role = Role(
            id="role-api-delete-any-only",
            name="api-delete-any-only",
            description="Legacy unrestricted delete permission only",
        )
        s.add(delete_any_role)
        await s.flush()
        delete_any_permission = (
            await s.execute(select(Permission).where(Permission.name == "knowledge:delete:any"))
        ).scalar_one()
        s.add(
            RolePermission(
                role_id=delete_any_role.id,
                permission_id=delete_any_permission.id,
            )
        )
        await role_repo.assign_role(delete_any_row.id, delete_any_role.id)
        personas["delete_any"] = User(
            user_id=delete_any_row.id,
            email="delete-any@x",
            name="delete-any",
            provider="ibm_ams",
        )
        await s.commit()

    rbac = RBACService(SessionLocal)
    fastapi_app = FastAPI()

    async def _stub_api_user(request: Request) -> User:
        return personas[request.headers.get("X-Test-Persona", "user")]

    fastapi_app.dependency_overrides[get_api_key_user_async] = _stub_api_user
    fastapi_app.dependency_overrides[get_rbac_service] = lambda: rbac
    # Stubbed so the real /v1 handler's sibling deps resolve; the gate still
    # raises 403 for a denied persona before the body runs.
    fastapi_app.dependency_overrides[get_session_manager] = lambda: object()

    @fastapi_app.get("/probe/users-delete")
    async def _probe_admin(user=Depends(require_api_key_permission("users:delete"))):
        return {"user_id": user.user_id}

    @fastapi_app.get("/probe/chat-use")
    async def _probe_chat(user=Depends(require_api_key_permission("chat:use"))):
        return {"user_id": user.user_id}

    @fastapi_app.get("/probe/kf-read")
    async def _probe_kf_read(user=Depends(require_api_key_permission("kf:read"))):
        return {"user_id": user.user_id}

    @fastapi_app.get("/probe/delete-document")
    async def _probe_delete_document(user=Depends(require_api_key_delete_permission)):
        return {"user_id": user.user_id}

    # A real gated /v1 handler. The gate runs as a dependency *before* the
    # handler body, so a denied request never reaches the delete core (no
    # service overrides needed for the 403 path).
    fastapi_app.add_api_route("/v1/documents", delete_document_endpoint, methods=["DELETE"])
    # Real KF search handler — proves the kf:read gate is wired on /v1.
    fastapi_app.dependency_overrides[get_knowledge_filter_service] = lambda: object()
    fastapi_app.add_api_route("/v1/knowledge-filters/search", kf_search_endpoint, methods=["POST"])

    yield fastapi_app, personas
    await engine.dispose()


def _client(fastapi_app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app), base_url="http://t")


@pytest.mark.asyncio
async def test_kill_switch_off_bypasses(app, monkeypatch):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "false")
    fastapi_app, _ = app
    async with _client(fastapi_app) as c:
        # 'user' lacks users:delete, but the kill switch lets it through
        r = await c.get("/probe/users-delete", headers={"X-Test-Persona": "user"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_kill_switch_off_bypasses_api_key_any_permission(app, monkeypatch):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "false")
    fastapi_app, _ = app
    async with _client(fastapi_app) as c:
        r = await c.get("/probe/delete-document", headers={"X-Test-Persona": "user"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_passes_when_enforced(app, monkeypatch):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    fastapi_app, _ = app
    async with _client(fastapi_app) as c:
        r = await c.get("/probe/users-delete", headers={"X-Test-Persona": "admin"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_user_denied_when_enforced(app, monkeypatch):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    fastapi_app, _ = app
    async with _client(fastapi_app) as c:
        r = await c.get("/probe/users-delete", headers={"X-Test-Persona": "user"})
    assert r.status_code == 403
    assert r.json()["detail"]["required"] == "users:delete"


@pytest.mark.asyncio
async def test_user_passes_perm_it_holds(app, monkeypatch):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    fastapi_app, _ = app
    async with _client(fastapi_app) as c:
        r = await c.get("/probe/chat-use", headers={"X-Test-Persona": "user"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_kf_read_granted_to_every_builtin_role(app, monkeypatch):
    """All built-in roles (even viewer) hold kf:read, so KF search/get keep
    working for existing API consumers once the gate is enforced."""
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    fastapi_app, _ = app
    async with _client(fastapi_app) as c:
        for persona in ("admin", "user", "viewer"):
            r = await c.get("/probe/kf-read", headers={"X-Test-Persona": persona})
            assert r.status_code == 200, persona


@pytest.mark.asyncio
async def test_real_v1_kf_search_gated_on_kf_read(app, monkeypatch):
    """End-to-end wiring: POST /v1/knowledge-filters/search now requires
    kf:read instead of accepting any authenticated caller."""
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    fastapi_app, _ = app
    async with _client(fastapi_app) as c:
        r = await c.post(
            "/v1/knowledge-filters/search",
            json={"query": ""},
            headers={"X-Test-Persona": "norole"},
        )
    assert r.status_code == 403
    assert r.json()["detail"]["required"] == "kf:read"


@pytest.mark.asyncio
async def test_real_v1_delete_blocks_viewer(app, monkeypatch):
    """The v1 delete endpoint accepts own or anonymous scope and rejects a viewer."""
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    fastapi_app, _ = app
    async with _client(fastapi_app) as c:
        r = await c.request(
            "DELETE",
            "/v1/documents",
            json={"filename": "x.txt"},
            headers={"X-Test-Persona": "viewer"},
        )
    assert r.status_code == 403
    assert r.json()["detail"]["required"] == [
        "knowledge:delete:own",
        "knowledge:delete:anonymous",
    ]


@pytest.mark.asyncio
async def test_real_v1_delete_blocks_delete_any_only_role(app, monkeypatch):
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    fastapi_app, _ = app
    async with _client(fastapi_app) as c:
        r = await c.request(
            "DELETE",
            "/v1/documents",
            json={"filename": "x.txt"},
            headers={"X-Test-Persona": "delete_any"},
        )
    assert r.status_code == 403
    assert r.json()["detail"]["required"] == [
        "knowledge:delete:own",
        "knowledge:delete:anonymous",
    ]
