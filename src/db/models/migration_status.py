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

"""Tracks one-shot runtime migrations (e.g. JSON->DB)."""

from datetime import datetime

from sqlmodel import Field, SQLModel


class MigrationStatus(SQLModel, table=True):
    __tablename__ = "migration_status"

    name: str = Field(primary_key=True, max_length=128)
    completed_at: datetime = Field(default_factory=datetime.utcnow)
    notes: str = Field(default="", max_length=2048)
