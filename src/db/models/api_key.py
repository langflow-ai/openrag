"""API key ORM (Phase 2 will move keys here from the OpenSearch index).

Placed in Phase 1 only as a forward-compatible schema; the existing
OpenSearch-backed APIKeyService is unchanged.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class ApiKey(SQLModel, table=True):
    __tablename__ = "api_keys"

    id: str = Field(primary_key=True, max_length=64)
    user_id: str = Field(foreign_key="users.id", max_length=64, index=True)
    name: str = Field(max_length=128)
    key_hash: str = Field(max_length=128, unique=True, index=True)
    key_prefix: str = Field(max_length=32)
    scope_role_ids: Optional[list] = Field(
        default=None, sa_column=Column("scope_role_ids", JSON, nullable=True)
    )
    last_used_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    revoked_at: Optional[datetime] = Field(default=None)
    revoked: bool = Field(default=False)
