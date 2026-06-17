"""Dev-only helper to swap the current user between built-in roles."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories import RoleRepo, UserRepo
from db.seed import BUILTIN_ROLES
from session_manager import User

_DEV_ROLES = frozenset(name for _id, name, _desc in BUILTIN_ROLES)


async def _resolve_db_user_id(session: AsyncSession, user: User) -> str | None:
    user_repo = UserRepo(session)
    db_user = await user_repo.get_by_oauth(user.provider or "unknown", user.user_id)
    if db_user is None:
        db_user = await user_repo.get_by_id(user.user_id)
    return db_user.id if db_user else None


async def set_dev_role(
    session: AsyncSession,
    user: User,
    role_name: str,
) -> list[str]:
    """Replace built-in role membership with a single built-in role. Returns new role names."""
    if role_name not in _DEV_ROLES:
        raise ValueError(f"Unsupported dev role: {role_name}")

    db_user_id = await _resolve_db_user_id(session, user)
    if db_user_id is None:
        raise ValueError("User not found in database")

    role_repo = RoleRepo(session)
    target = await role_repo.get_by_name(role_name)
    if target is None:
        raise ValueError(f"Role not found: {role_name}")

    for name in _DEV_ROLES:
        role = await role_repo.get_by_name(name)
        if role is not None:
            await role_repo.revoke_role(db_user_id, role.id)

    await role_repo.assign_role(db_user_id, target.id)

    roles = await role_repo.list_user_roles(db_user_id)
    return [r.name for r in roles]
