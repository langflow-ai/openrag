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

from sqlmodel import Field, SQLModel


class RolePermission(SQLModel, table=True):
    __tablename__ = "role_permissions"

    role_id: str = Field(
        foreign_key="roles.id",
        primary_key=True,
        max_length=64,
    )
    permission_id: str = Field(
        foreign_key="permissions.id",
        primary_key=True,
        max_length=64,
    )
