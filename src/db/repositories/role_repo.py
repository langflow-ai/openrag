from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from db.models import Permission, Role, RolePermission, UserRole


class RoleRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_name(self, name: str) -> Role | None:
        result = await self.session.execute(select(Role).where(col(Role.name) == name))
        return result.scalar_one_or_none()

    async def list_user_roles(self, user_id: str) -> list[Role]:
        result = await self.session.execute(
            select(Role)
            .join(UserRole, col(UserRole.role_id) == col(Role.id))
            .where(col(UserRole.user_id) == user_id)
        )
        return list(result.scalars().all())

    async def list_permissions_for_user(self, user_id: str) -> set[str]:
        result = await self.session.execute(
            select(col(Permission.name))
            .join(RolePermission, col(RolePermission.permission_id) == col(Permission.id))
            .join(UserRole, col(UserRole.role_id) == col(RolePermission.role_id))
            .where(col(UserRole.user_id) == user_id)
        )
        return set(result.scalars().all())

    async def list_permissions_for_role_ids(self, role_ids: list[str]) -> set[str]:
        if not role_ids:
            return set()
        result = await self.session.execute(
            select(col(Permission.name))
            .join(RolePermission, col(RolePermission.permission_id) == col(Permission.id))
            .where(col(RolePermission.role_id).in_(role_ids))
        )
        return set(result.scalars().all())

    async def assign_role(
        self, user_id: str, role_id: str, granted_by: str | None = None
    ) -> UserRole:
        existing = await self.session.execute(
            select(UserRole).where(
                col(UserRole.user_id) == user_id, col(UserRole.role_id) == role_id
            )
        )
        row = existing.scalar_one_or_none()
        if row:
            return row
        ur = UserRole(user_id=user_id, role_id=role_id, granted_by=granted_by)
        self.session.add(ur)
        await self.session.flush()
        return ur

    async def revoke_role(self, user_id: str, role_id: str) -> None:
        result = await self.session.execute(
            select(UserRole).where(
                col(UserRole.user_id) == user_id, col(UserRole.role_id) == role_id
            )
        )
        row = result.scalar_one_or_none()
        if row:
            await self.session.delete(row)
            await self.session.flush()
