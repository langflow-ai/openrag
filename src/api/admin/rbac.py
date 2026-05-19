"""Admin RBAC endpoints.

Owns:
  GET    /api/admin/users
  GET    /api/admin/users/{id}
  PATCH  /api/admin/users/{id}
  DELETE /api/admin/users/{id}
  POST   /api/admin/users/{id}/roles            body: {role_id}
  DELETE /api/admin/users/{id}/roles/{role_id}

  GET    /api/admin/roles
  POST   /api/admin/roles                        body: {name, description, permissions[]}
  PATCH  /api/admin/roles/{id}                   body: {description?, permissions?[]}
  DELETE /api/admin/roles/{id}
  GET    /api/admin/permissions

  GET    /api/admin/audit                        ?limit=100&offset=0

Every mutation writes an audit_log row inside the same DB transaction.
Cache invalidation: any role/permission mutation calls
`rbac.invalidate(user_id)` for the affected user (or `invalidate_all()`
for permission-catalog changes).
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    AuditLog,
    Permission,
    Role,
    RolePermission,
    User as UserRow,
    UserRole,
)
from db.repositories import (
    AuditRepo,
    PermissionRepo,
    RoleRepo,
    UserRepo,
)
from dependencies import (
    get_current_user,
    get_db_session,
    get_rbac_service,
    invalidate_user_ensured_cache,
    require_permission,
)
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)

# See note in api/users.py — Next.js proxy strips /api before forwarding,
# so we mount under /admin and the frontend reaches us at /api/admin/...
router = APIRouter(prefix="/admin", tags=["admin"])


def _require_rbac_ui() -> None:
    """Gate dependency: 404 when the local RBAC UI is disabled.

    Applied to every role-mutation, role-CRUD, permissions-list, and
    audit endpoint. GET /admin/users and GET /admin/users/{id} are
    deliberately left open so the read-only users list can render in
    saas/on_prem deployments.
    """
    from config.settings import OPENRAG_RBAC_UI_ENABLED

    if not OPENRAG_RBAC_UI_ENABLED:
        raise HTTPException(status_code=404, detail="Not Found")


# ---------------------------------------------------------------------------
# Pydantic shapes
# ---------------------------------------------------------------------------

class UserOut(BaseModel):
    id: str
    oauth_provider: str
    oauth_subject: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    picture_url: Optional[str] = None
    is_active: bool
    roles: List[str]
    created_at: Optional[str] = None
    last_login: Optional[str] = None


class UserPatch(BaseModel):
    is_active: Optional[bool] = None


class AssignRoleBody(BaseModel):
    role_id: str


class RoleOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_system: bool
    permissions: List[str]


class RoleCreateBody(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: List[str] = []


class RolePatchBody(BaseModel):
    description: Optional[str] = None
    permissions: Optional[List[str]] = None


class PermissionOut(BaseModel):
    id: str
    name: str
    resource: str
    action: str
    description: Optional[str] = None


class AuditOut(BaseModel):
    id: str
    ts: str
    actor_user_id: Optional[str] = None
    event: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    audit_metadata: Optional[dict] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _user_to_out(session: AsyncSession, row: UserRow) -> UserOut:
    role_repo = RoleRepo(session)
    roles = await role_repo.list_user_roles(row.id)
    return UserOut(
        id=row.id,
        oauth_provider=row.oauth_provider,
        oauth_subject=row.oauth_subject,
        email=row.email,
        display_name=row.display_name,
        picture_url=row.picture_url,
        is_active=row.is_active,
        roles=[r.name for r in roles],
        created_at=row.created_at.isoformat() if row.created_at else None,
        last_login=row.last_login.isoformat() if row.last_login else None,
    )


def _audit_to_out(row: AuditLog) -> AuditOut:
    return AuditOut(
        id=row.id,
        ts=row.ts.isoformat() if row.ts else "",
        actor_user_id=row.actor_user_id,
        event=row.event,
        target_type=row.target_type,
        target_id=row.target_id,
        audit_metadata=row.audit_metadata,
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@router.get("/users", response_model=List[UserOut])
async def list_users(
    limit: int = 100,
    offset: int = 0,
    actor: User = Depends(require_permission("users:list")),
    session: AsyncSession = Depends(get_db_session),
) -> List[UserOut]:
    user_repo = UserRepo(session)
    rows = await user_repo.list_all(limit=limit, offset=offset)
    return [await _user_to_out(session, r) for r in rows]


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(
    user_id: str,
    actor: User = Depends(require_permission("users:read")),
    session: AsyncSession = Depends(get_db_session),
) -> UserOut:
    row = await UserRepo(session).get_by_id(user_id)
    if row is None:
        raise HTTPException(404, {"error": "user_not_found"})
    return await _user_to_out(session, row)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    body: UserPatch,
    request: Request,
    _gate: None = Depends(_require_rbac_ui),
    actor: User = Depends(require_permission("users:invite")),
    session: AsyncSession = Depends(get_db_session),
    rbac=Depends(get_rbac_service),
) -> UserOut:
    row = await UserRepo(session).get_by_id(user_id)
    if row is None:
        raise HTTPException(404, {"error": "user_not_found"})

    # Don't let the operator deactivate the last active admin.
    if body.is_active is False and row.is_active:
        role_repo = RoleRepo(session)
        roles = await role_repo.list_user_roles(user_id)
        if any(r.name == "admin" for r in roles):
            if await role_repo.count_admins() <= 1:
                raise HTTPException(
                    400, {"error": "cannot_deactivate_last_admin"}
                )

    changed: dict = {}
    if body.is_active is not None and body.is_active != row.is_active:
        row.is_active = body.is_active
        changed["is_active"] = body.is_active

    if changed:
        session.add(row)
        await AuditRepo(session).write(
            event="user.updated",
            actor_user_id=actor.user_id,
            target_type="user",
            target_id=row.id,
            audit_metadata={"changes": changed},
            ip=request.client.host if request.client else None,
        )
        await session.commit()
        rbac.invalidate(row.id)
        invalidate_user_ensured_cache(row.oauth_provider, row.oauth_subject)

    return await _user_to_out(session, row)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    request: Request,
    _gate: None = Depends(_require_rbac_ui),
    actor: User = Depends(require_permission("users:delete")),
    session: AsyncSession = Depends(get_db_session),
    rbac=Depends(get_rbac_service),
):
    if actor.user_id == user_id:
        raise HTTPException(400, {"error": "cannot_delete_self"})

    row = await UserRepo(session).get_by_id(user_id)
    if row is None:
        raise HTTPException(404, {"error": "user_not_found"})

    # Capture identity for the post-commit cache invalidation; after
    # session.delete(row) + commit the row is expunged and these
    # attributes become unavailable.
    deleted_provider = row.oauth_provider
    deleted_subject = row.oauth_subject

    # Don't let the operator delete the last admin.
    role_repo = RoleRepo(session)
    roles = await role_repo.list_user_roles(user_id)
    if any(r.name == "admin" for r in roles):
        if await role_repo.count_admins() <= 1:
            raise HTTPException(400, {"error": "cannot_delete_last_admin"})

    # Pre-null audit_log.actor_user_id so the audit row written below
    # for the delete event survives even after the deleted user's other
    # historical audit rows are nulled by the SET NULL FK policy. (The
    # FK migration handles the cascade from the DB side; this explicit
    # nulling is belt-and-suspenders for older deployments where the
    # 0005_user_fk_ondelete migration hasn't run yet.)
    await session.execute(
        update(AuditLog)
        .where(AuditLog.actor_user_id == user_id)
        .values(actor_user_id=None)
    )
    # The 0005 migration sets ON DELETE CASCADE for user_roles and
    # user_preferences and ON DELETE SET NULL for granted_by /
    # workspace_config.updated_by, so a single delete of the user row
    # propagates correctly. Keep the explicit deletes for the legacy
    # path (deployments that haven't applied 0005 yet); they're no-ops
    # under the new FK policy.
    await session.execute(
        UserRole.__table__.delete().where(UserRole.user_id == user_id)
    )
    from db.models import UserPreferences
    await session.execute(
        UserPreferences.__table__.delete().where(UserPreferences.user_id == user_id)
    )
    await session.delete(row)

    await AuditRepo(session).write(
        event="user.deleted",
        actor_user_id=actor.user_id,
        target_type="user",
        target_id=user_id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    rbac.invalidate(user_id)
    invalidate_user_ensured_cache(deleted_provider, deleted_subject)
    return {"success": True}


@router.post("/users/{user_id}/roles", response_model=UserOut)
async def assign_role(
    user_id: str,
    body: AssignRoleBody,
    request: Request,
    _gate: None = Depends(_require_rbac_ui),
    actor: User = Depends(require_permission("roles:assign")),
    session: AsyncSession = Depends(get_db_session),
    rbac=Depends(get_rbac_service),
) -> UserOut:
    user_repo = UserRepo(session)
    role_repo = RoleRepo(session)

    user = await user_repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(404, {"error": "user_not_found"})
    role = await role_repo.get_by_id(body.role_id)
    if role is None:
        raise HTTPException(404, {"error": "role_not_found"})

    await role_repo.assign_role(user_id, body.role_id, granted_by=actor.user_id)
    await AuditRepo(session).write(
        event="user.role.assigned",
        actor_user_id=actor.user_id,
        target_type="user",
        target_id=user_id,
        audit_metadata={"role_id": body.role_id, "role_name": role.name},
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    rbac.invalidate(user_id)
    return await _user_to_out(session, user)


@router.delete("/users/{user_id}/roles/{role_id}", response_model=UserOut)
async def revoke_role(
    user_id: str,
    role_id: str,
    request: Request,
    _gate: None = Depends(_require_rbac_ui),
    actor: User = Depends(require_permission("roles:assign")),
    session: AsyncSession = Depends(get_db_session),
    rbac=Depends(get_rbac_service),
) -> UserOut:
    user_repo = UserRepo(session)
    role_repo = RoleRepo(session)
    user = await user_repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(404, {"error": "user_not_found"})
    role = await role_repo.get_by_id(role_id)

    # Don't let the operator strip the last admin.
    if role and role.name == "admin":
        admin_count = await role_repo.count_admins()
        if admin_count <= 1:
            raise HTTPException(400, {"error": "cannot_remove_last_admin"})

    await role_repo.revoke_role(user_id, role_id)
    await AuditRepo(session).write(
        event="user.role.revoked",
        actor_user_id=actor.user_id,
        target_type="user",
        target_id=user_id,
        audit_metadata={"role_id": role_id, "role_name": role.name if role else None},
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    rbac.invalidate(user_id)
    return await _user_to_out(session, user)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


async def _role_to_out(session: AsyncSession, role: Role) -> RoleOut:
    perms = await RoleRepo(session).list_permissions_for_role(role.id)
    return RoleOut(
        id=role.id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions=[p.name for p in perms],
    )


@router.get("/roles", response_model=List[RoleOut])
async def list_roles(
    _gate: None = Depends(_require_rbac_ui),
    actor: User = Depends(require_permission("roles:list")),
    session: AsyncSession = Depends(get_db_session),
) -> List[RoleOut]:
    roles = await RoleRepo(session).list_all()
    return [await _role_to_out(session, r) for r in roles]


@router.post("/roles", response_model=RoleOut)
async def create_role(
    body: RoleCreateBody,
    request: Request,
    _gate: None = Depends(_require_rbac_ui),
    actor: User = Depends(require_permission("roles:create")),
    session: AsyncSession = Depends(get_db_session),
    rbac=Depends(get_rbac_service),
) -> RoleOut:
    role_repo = RoleRepo(session)
    perm_repo = PermissionRepo(session)

    if not body.name or len(body.name) > 64:
        raise HTTPException(400, {"error": "invalid_role_name"})

    existing = await role_repo.get_by_name(body.name)
    if existing is not None:
        raise HTTPException(409, {"error": "role_exists"})

    role = Role(
        id=str(uuid.uuid4()),
        name=body.name,
        description=body.description,
        is_system=False,
    )
    session.add(role)
    await session.flush()

    # Resolve permissions by name → id
    if body.permissions:
        for pname in body.permissions:
            perm = await perm_repo.get_by_name(pname)
            if perm is None:
                raise HTTPException(400, {"error": "unknown_permission", "name": pname})
            session.add(RolePermission(role_id=role.id, permission_id=perm.id))

    await AuditRepo(session).write(
        event="role.created",
        actor_user_id=actor.user_id,
        target_type="role",
        target_id=role.id,
        audit_metadata={"name": role.name, "permissions": body.permissions},
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    rbac.invalidate_all()
    return await _role_to_out(session, role)


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: str,
    body: RolePatchBody,
    request: Request,
    _gate: None = Depends(_require_rbac_ui),
    actor: User = Depends(require_permission("roles:edit")),
    session: AsyncSession = Depends(get_db_session),
    rbac=Depends(get_rbac_service),
) -> RoleOut:
    role_repo = RoleRepo(session)
    perm_repo = PermissionRepo(session)

    role = await role_repo.get_by_id(role_id)
    if role is None:
        raise HTTPException(404, {"error": "role_not_found"})

    changed: dict = {}
    if body.description is not None and body.description != role.description:
        role.description = body.description
        changed["description"] = body.description
        session.add(role)

    if body.permissions is not None:
        # Resolve names; fail fast on any unknown.
        new_perm_ids: list[str] = []
        for pname in body.permissions:
            perm = await perm_repo.get_by_name(pname)
            if perm is None:
                raise HTTPException(400, {"error": "unknown_permission", "name": pname})
            new_perm_ids.append(perm.id)

        # Replace the role's permission set. For is_system roles we still
        # allow this so admins can adjust defaults — they just can't rename
        # or delete the role.
        await session.execute(
            RolePermission.__table__.delete().where(RolePermission.role_id == role.id)
        )
        for pid in new_perm_ids:
            session.add(RolePermission(role_id=role.id, permission_id=pid))
        changed["permissions"] = body.permissions

    if changed:
        await AuditRepo(session).write(
            event="role.updated",
            actor_user_id=actor.user_id,
            target_type="role",
            target_id=role.id,
            audit_metadata={"changes": changed},
            ip=request.client.host if request.client else None,
        )
        await session.commit()
        rbac.invalidate_all()
    return await _role_to_out(session, role)


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: str,
    request: Request,
    _gate: None = Depends(_require_rbac_ui),
    actor: User = Depends(require_permission("roles:delete")),
    session: AsyncSession = Depends(get_db_session),
    rbac=Depends(get_rbac_service),
):
    role_repo = RoleRepo(session)
    role = await role_repo.get_by_id(role_id)
    if role is None:
        raise HTTPException(404, {"error": "role_not_found"})
    if role.is_system:
        raise HTTPException(400, {"error": "cannot_delete_system_role"})

    await session.execute(
        RolePermission.__table__.delete().where(RolePermission.role_id == role.id)
    )
    await session.execute(
        UserRole.__table__.delete().where(UserRole.role_id == role.id)
    )
    await session.delete(role)
    await AuditRepo(session).write(
        event="role.deleted",
        actor_user_id=actor.user_id,
        target_type="role",
        target_id=role.id,
        audit_metadata={"name": role.name},
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    rbac.invalidate_all()
    return {"success": True}


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


@router.get("/permissions", response_model=List[PermissionOut])
async def list_permissions(
    _gate: None = Depends(_require_rbac_ui),
    actor: User = Depends(require_permission("roles:list")),
    session: AsyncSession = Depends(get_db_session),
) -> List[PermissionOut]:
    perms = await PermissionRepo(session).list_all()
    return [
        PermissionOut(
            id=p.id, name=p.name, resource=p.resource, action=p.action,
            description=p.description,
        )
        for p in perms
    ]


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


@router.get("/audit", response_model=List[AuditOut])
async def list_audit(
    limit: int = 100,
    offset: int = 0,
    _gate: None = Depends(_require_rbac_ui),
    actor: User = Depends(require_permission("audit:read")),
    session: AsyncSession = Depends(get_db_session),
) -> List[AuditOut]:
    rows = await AuditRepo(session).list_recent(limit=limit, offset=offset)
    return [_audit_to_out(r) for r in rows]
