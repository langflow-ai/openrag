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

from typing import Optional

from sqlmodel import Field, SQLModel


class Permission(SQLModel, table=True):
    __tablename__ = "permissions"

    id: str = Field(primary_key=True, max_length=64)
    name: str = Field(max_length=128, unique=True, index=True)
    resource: str = Field(max_length=64, index=True)
    action: str = Field(max_length=64)
    description: str | None = Field(default=None, max_length=512)
