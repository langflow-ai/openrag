import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLog


class AuditRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def write(
        self,
        event: str,
        actor_user_id: Optional[str] = None,
        actor_api_key_id: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        audit_metadata: Optional[dict] = None,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        row = AuditLog(
            id=str(uuid.uuid4()),
            event=event,
            actor_user_id=actor_user_id,
            actor_api_key_id=actor_api_key_id,
            target_type=target_type,
            target_id=target_id,
            audit_metadata=audit_metadata,
            ip=ip,
            user_agent=user_agent,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_recent(self, limit: int = 100, offset: int = 0) -> list[AuditLog]:
        result = await self.session.execute(
            select(AuditLog).order_by(AuditLog.ts.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all())
