"""Async CRUD over the ``workspace_config`` table.

Each row is one logical section ('providers' | 'knowledge' | 'agent' |
'onboarding' | 'meta'). The repo speaks plain dicts — serialization
to/from ``OpenRAGConfig`` is the service's job.
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import WorkspaceConfig

# Section names recognized by the migration / service.
SECTIONS = ("providers", "knowledge", "agent", "onboarding", "meta")


class WorkspaceConfigRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_section(self, section: str) -> Optional[dict[str, Any]]:
        row = await self.session.get(WorkspaceConfig, section)
        return None if row is None else (row.value or {})

    async def list_all(self) -> dict[str, dict[str, Any]]:
        result = await self.session.execute(select(WorkspaceConfig))
        return {row.section: (row.value or {}) for row in result.scalars().all()}

    async def upsert(
        self,
        section: str,
        value: dict[str, Any],
        actor_user_id: Optional[str] = None,
    ) -> WorkspaceConfig:
        existing = await self.session.get(WorkspaceConfig, section)
        if existing is None:
            row = WorkspaceConfig(
                section=section,
                value=value,
                updated_at=datetime.utcnow(),
                updated_by=actor_user_id,
            )
            self.session.add(row)
            await self.session.flush()
            return row
        existing.value = value
        existing.updated_at = datetime.utcnow()
        if actor_user_id is not None:
            existing.updated_by = actor_user_id
        self.session.add(existing)
        await self.session.flush()
        return existing

    async def has_any(self) -> bool:
        """Quick check for the migration: do we have any rows?"""
        result = await self.session.execute(select(WorkspaceConfig).limit(1))
        return result.scalar_one_or_none() is not None
