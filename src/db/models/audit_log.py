# ******************************************************************************
# IBM Confidential
#
# OCO Source Materials
#
#  Copyright IBM Corp. 2026  All Rights Reserved.
#
# The source code for this program is not published or otherwise divested
# of its trade secrets, irrespective of what has been deposited with
# the U.S. Copyright Office.
# ******************************************************************************

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: str = Field(primary_key=True, max_length=64)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    actor_user_id: str | None = Field(
        default=None, foreign_key="users.id", max_length=64, index=True
    )
    actor_api_key_id: str | None = Field(default=None, max_length=64)
    event: str = Field(max_length=128, index=True)
    target_type: str | None = Field(default=None, max_length=64)
    target_id: str | None = Field(default=None, max_length=128)
    audit_metadata: dict | None = Field(
        default=None, sa_column=Column("metadata", JSON, nullable=True)
    )
    ip: str | None = Field(default=None, max_length=64)
    user_agent: str | None = Field(default=None, max_length=512)
