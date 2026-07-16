"""Persistence interface for the custom metadata field catalog."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.metadata_field import MetadataField


class MetadataFieldRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str) -> MetadataField | None:
        return await self.session.get(MetadataField, key)

    async def list_all(self) -> list[MetadataField]:
        result = await self.session.execute(select(MetadataField).order_by(MetadataField.key))
        return list(result.scalars().all())

    async def add(self, key: str, metadata_type: str) -> MetadataField:
        row = MetadataField(
            key=key,
            metadata_type=metadata_type,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.flush()
        return row
