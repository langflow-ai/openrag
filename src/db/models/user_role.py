from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class UserRole(SQLModel, table=True):
    __tablename__ = "user_roles"

    user_id: str = Field(
        foreign_key="users.id",
        primary_key=True,
        max_length=64,
    )
    role_id: str = Field(
        foreign_key="roles.id",
        primary_key=True,
        max_length=64,
    )
    granted_by: Optional[str] = Field(
        default=None, foreign_key="users.id", max_length=64
    )
    granted_at: datetime = Field(default_factory=datetime.utcnow)
