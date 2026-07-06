from typing import Optional

from sqlmodel import Field, SQLModel


class Permission(SQLModel, table=True):
    __tablename__ = "permissions"

    id: str = Field(primary_key=True, max_length=64)
    name: str = Field(max_length=128, unique=True, index=True)
    resource: str = Field(max_length=64, index=True)
    action: str = Field(max_length=64)
    description: Optional[str] = Field(default=None, max_length=512)
