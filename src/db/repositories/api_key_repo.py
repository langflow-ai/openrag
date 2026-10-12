"""ApiKey repo — placeholder for Phase 2.

Phase 1 ships the schema only. Existing OpenSearch-backed APIKeyService
remains the source of truth until Phase 2 migrates keys here.
"""

from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from db.models import ApiKey


class ApiKeyRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    # TODO: once we remove opensearch fallback for reads, we can revert this to
    # get_by_hash to only return non revoked keys
    async def get_by_hash_any_state(self, key_hash: str) -> ApiKey | None:
        result = await self.session.execute(select(ApiKey).where(col(ApiKey.key_hash) == key_hash))
        return result.scalar_one_or_none()

    async def get_by_id(self, key_id: str) -> ApiKey | None:
        return await self.session.get(ApiKey, key_id)

    async def list_for_user(self, user_id: str) -> list[ApiKey]:
        result = await self.session.execute(select(ApiKey).where(col(ApiKey.user_id) == user_id))
        return list(result.scalars().all())

    async def add(self, api_key: ApiKey) -> ApiKey:
        self.session.add(api_key)
        await self.session.flush()
        return api_key

    async def mark_used(self, key_id: str) -> None:
        """Update last_used_at on a successful validation"""
        from datetime import UTC, datetime

        row = await self.session.get(ApiKey, key_id)
        if row is None:
            return

        row.last_used_at = datetime.now(UTC)
        self.session.add(row)
        await self.session.flush()

    async def revoke(self, key_id: str) -> None:
        from datetime import datetime

        row = await self.session.get(ApiKey, key_id)
        if row:
            row.revoked = True
            row.revoked_at = datetime.now(UTC)
            self.session.add(row)
            await self.session.flush()

    # TODO: once we remove opensearch fallback for reads, add a hard delete sql method
