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
