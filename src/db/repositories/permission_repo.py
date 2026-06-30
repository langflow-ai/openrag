# ******************************************************************************
# IBM Confidential
#
# OCO Source Materials
#
#  Copyright IBM Corp. 2026  All Rights Reserved.
#
# The source code for this program is not published or otherwise divested
# of its trade secrets, irrespective of what has been deposited with
# the U.S. Copyright Office.
# ******************************************************************************

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Permission


class PermissionRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(self) -> list[Permission]:
        result = await self.session.execute(
            select(Permission).order_by(Permission.resource, Permission.action)
        )
        return list(result.scalars().all())

    async def get_by_name(self, name: str) -> Optional[Permission]:
        result = await self.session.execute(
            select(Permission).where(Permission.name == name)
        )
        return result.scalar_one_or_none()
