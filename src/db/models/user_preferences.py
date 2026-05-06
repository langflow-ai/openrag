from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from db.types import EncryptedString


class UserPreferences(SQLModel, table=True):
    __tablename__ = "user_preferences"

    user_id: str = Field(
        foreign_key="users.id",
        primary_key=True,
        max_length=64,
    )

    agent_system_prompt_override: Optional[str] = Field(
        default=None,
        sa_column=Column(
            "agent_system_prompt_override",
            EncryptedString(tenant_id="user_pref"),
            nullable=True,
        ),
    )
    default_kf_id: Optional[str] = Field(default=None, max_length=128)
    theme: Optional[str] = Field(default=None, max_length=32)
    language: Optional[str] = Field(default=None, max_length=16)

    # JSON blob: {"openai":{"api_key":"..."}, "anthropic":{...}}
    provider_overrides: Optional[str] = Field(
        default=None,
        sa_column=Column(
            "provider_overrides",
            EncryptedString(tenant_id="user_pref"),
            nullable=True,
        ),
    )

    # Future-proof bag for additional opt-in preferences.
    preferences_json: Optional[str] = Field(
        default=None,
        sa_column=Column(
            "preferences_json",
            EncryptedString(tenant_id="user_pref"),
            nullable=True,
        ),
    )

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
