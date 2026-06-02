"""User ORM model.

PII columns (email, display_name) use EncryptedString. email_lookup_hash
is a deterministic SHA-256 of the lowercase email so we keep a unique
constraint and exact-match lookup despite the encrypted blob.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from db.types import EncryptedString


class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("oauth_provider", "oauth_subject", name="uq_users_oauth"),
    )

    id: str = Field(primary_key=True, max_length=64)
    oauth_provider: str = Field(max_length=32, index=True)
    oauth_subject: str = Field(max_length=255, index=True)

    email: Optional[str] = Field(
        default=None,
        sa_column=Column("email", EncryptedString(tenant_id="user_pii"), nullable=True),
    )
    email_lookup_hash: Optional[str] = Field(
        default=None, max_length=64, unique=True, index=True
    )
    display_name: Optional[str] = Field(
        default=None,
        sa_column=Column(
            "display_name", EncryptedString(tenant_id="user_pii"), nullable=True
        ),
    )
    picture_url: Optional[str] = Field(default=None, max_length=2048)

    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = Field(default=None)
