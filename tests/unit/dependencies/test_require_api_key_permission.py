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
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from api.v1.documents import delete_document_endpoint  # noqa: E402
from db.repositories import RoleRepo  # noqa: E402
from db.seed import seed_roles_and_permissions  # noqa: E402
from dependencies import (  # noqa: E402
    get_api_key_user_async,
    get_rbac_service,
    get_session_manager,
    require_api_key_permission,
)
from services.rbac_service import RBACService  # noqa: E402
from services.user_service import ensure_user_row  # noqa: E402
from session_manager import User  # noqa: E402


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

    # A real gated /v1 handler. The gate runs as a dependency *before* the
    # handler body, so a denied request never reaches the delete core (no
    # service overrides needed for the 403 path).
    fastapi_app.add_api_route("/v1/documents", delete_document_endpoint, methods=["DELETE"])

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
async def test_real_v1_delete_blocks_viewer(app, monkeypatch):
    """End-to-end wiring: DELETE /v1/documents is gated on knowledge:delete:own.
    A viewer lacks it, so the real handler returns 403 from the gate before the
    body runs."""
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
    assert r.json()["detail"]["required"] == "knowledge:delete:own"
