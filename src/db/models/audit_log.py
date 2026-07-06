from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: str = Field(primary_key=True, max_length=64)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    actor_user_id: Optional[str] = Field(
        default=None, foreign_key="users.id", max_length=64, index=True
    )
    actor_api_key_id: Optional[str] = Field(default=None, max_length=64)
    event: str = Field(max_length=128, index=True)
    target_type: Optional[str] = Field(default=None, max_length=64)
    target_id: Optional[str] = Field(default=None, max_length=128)
    audit_metadata: Optional[dict] = Field(
        default=None, sa_column=Column("metadata", JSON, nullable=True)
    )
    ip: Optional[str] = Field(default=None, max_length=64)
    user_agent: Optional[str] = Field(default=None, max_length=512)
