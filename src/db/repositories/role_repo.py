from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Permission, Role, RolePermission, UserRole


class RoleRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_name(self, name: str) -> Optional[Role]:
        result = await self.session.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()

    async def get_by_id(self, role_id: str) -> Optional[Role]:
        return await self.session.get(Role, role_id)

    async def list_all(self) -> list[Role]:
        result = await self.session.execute(select(Role).order_by(Role.name))
        return list(result.scalars().all())

    async def count_admins(self) -> int:
        result = await self.session.execute(
            select(UserRole)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.name == "admin")
        )
        return len(list(result.scalars().all()))

    async def list_user_roles(self, user_id: str) -> list[Role]:
        result = await self.session.execute(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        return list(result.scalars().all())

    async def list_permissions_for_role(self, role_id: str) -> list[Permission]:
        result = await self.session.execute(
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
        )
        return list(result.scalars().all())

    async def list_permissions_for_user(self, user_id: str) -> set[str]:
        result = await self.session.execute(
            select(Permission.name)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        return set(result.scalars().all())

    async def list_permissions_for_role_ids(self, role_ids: list[str]) -> set[str]:
        if not role_ids:
            return set()
        result = await self.session.execute(
            select(Permission.name)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id.in_(role_ids))
        )
        return set(result.scalars().all())

    async def assign_role(
        self, user_id: str, role_id: str, granted_by: Optional[str] = None
    ) -> UserRole:
        existing = await self.session.execute(
            select(UserRole).where(
                UserRole.user_id == user_id, UserRole.role_id == role_id
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
                UserRole.user_id == user_id, UserRole.role_id == role_id
            )
        )
        row = result.scalar_one_or_none()
        if row:
            await self.session.delete(row)
            await self.session.flush()
