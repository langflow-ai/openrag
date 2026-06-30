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

from sqlmodel import Field, SQLModel


class Role(SQLModel, table=True):
    __tablename__ = "roles"

    id: str = Field(primary_key=True, max_length=64)
    name: str = Field(max_length=64, unique=True, index=True)
    description: Optional[str] = Field(default=None, max_length=512)
    is_system: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
