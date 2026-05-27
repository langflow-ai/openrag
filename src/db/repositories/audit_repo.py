import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLog


class AuditRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def write(
        self,
        event: str,
        actor_user_id: str | None = None,
        actor_api_key_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        audit_metadata: dict | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
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
