"""ApiKey repo — placeholder for Phase 2.

Phase 1 ships the schema only. Existing OpenSearch-backed APIKeyService
remains the source of truth until Phase 2 migrates keys here.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey


class ApiKeyRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked.is_(False))
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: str) -> list[ApiKey]:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.user_id == user_id)
        )
        return list(result.scalars().all())

    async def add(self, api_key: ApiKey) -> ApiKey:
        self.session.add(api_key)
        await self.session.flush()
        return api_key

    async def revoke(self, key_id: str) -> None:
        from datetime import datetime
        row = await self.session.get(ApiKey, key_id)
        if row:
            row.revoked = True
            row.revoked_at = datetime.utcnow()
            self.session.add(row)
            await self.session.flush()
