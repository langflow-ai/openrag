"""Per-user identity endpoints.

GET /api/users/me              -> profile of the current user
GET /api/users/me/permissions  -> list of permission strings
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories import PermissionRepo, RoleRepo, UserRepo
from dependencies import get_current_user, get_db_session, get_rbac_service
from services.rbac_service import is_rbac_enforced
from session_manager import User


async def _effective_permissions(rbac, db_id: str, session: AsyncSession) -> set[str]:
    """Return the permissions the UI should treat the user as having.

    When ``OPENRAG_RBAC_ENFORCE=false``, the backend lets every
    authenticated user through every gate, so the frontend should also
    show every action — otherwise users see disabled buttons that
    actually work. We return the full permission catalog from the DB.
    """
    if is_rbac_enforced():
        return await rbac.get_user_permissions(db_id)
    perms = await PermissionRepo(session).list_all()
    return {p.name for p in perms}


# Backend routes are mounted WITHOUT the /api prefix because the Next.js
# proxy at frontend/app/api/[...path]/route.ts strips it before forwarding.
# Frontend reaches these via /api/users/me, /api/users/me/permissions.
router = APIRouter(prefix="/users", tags=["users"])


class MeResponse(BaseModel):
    user_id: str
    email: str
    name: str
    picture: str | None = None
    provider: str
    roles: list[str]
    permissions: list[str]
    # OPENRAG_RBAC_ENFORCE — surfaced so the UI can hide RBAC-only
    # sections (Users & Roles, Audit log, role pills) when the
    # operator has the kill switch off.
    rbac_enforced: bool


@router.get("/me", response_model=MeResponse)
async def get_me(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    rbac=Depends(get_rbac_service),
) -> MeResponse:
    role_repo = RoleRepo(session)
    user_repo = UserRepo(session)

    # Resolve internal DB id from oauth identity (legacy rows used user_id directly).
    db_user = await user_repo.get_by_oauth(user.provider or "unknown", user.user_id)
    if db_user is None:
        db_user = await user_repo.get_by_id(user.user_id)
    db_id = db_user.id if db_user else user.user_id

    roles = await role_repo.list_user_roles(db_id)
    perms = await _effective_permissions(rbac, db_id, session)

    return MeResponse(
        user_id=user.user_id,
        email=user.email or "",
        name=user.name or "",
        picture=user.picture,
        provider=user.provider or "unknown",
        roles=[r.name for r in roles],
        permissions=sorted(perms),
        rbac_enforced=is_rbac_enforced(),
    )


class PermissionsResponse(BaseModel):
    permissions: list[str]


@router.get("/me/permissions", response_model=PermissionsResponse)
async def get_my_permissions(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    rbac=Depends(get_rbac_service),
) -> PermissionsResponse:
    user_repo = UserRepo(session)
    db_user = await user_repo.get_by_oauth(user.provider or "unknown", user.user_id)
    if db_user is None:
        db_user = await user_repo.get_by_id(user.user_id)
    db_id = db_user.id if db_user else user.user_id

    perms = await _effective_permissions(rbac, db_id, session)
    return PermissionsResponse(permissions=sorted(perms))
