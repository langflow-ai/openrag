"""Workspace-level config storage.

One row per logical section ('providers' | 'knowledge' | 'agent' |
'onboarding' | 'meta'). The `value` JSON column holds the section's
payload — the same shape the existing ``OpenRAGConfig.to_dict()``
produces for that section, so the migration is a 1:1 copy of what
lives in ``config/config.yaml`` today.

Provider api_key fields stay encrypted via ``encrypt_secret`` inside
the JSON envelope; no DB-level encryption is added here because the
other fields (embedding model, prompt, etc.) are not secrets.
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class WorkspaceConfig(SQLModel, table=True):
    __tablename__ = "workspace_config"

    section: str = Field(primary_key=True, max_length=64)
    value: Optional[dict[str, Any]] = Field(
        default_factory=dict,
        sa_column=Column("value", JSON, nullable=False),
    )
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = Field(
        default=None, foreign_key="users.id", max_length=64
    )
