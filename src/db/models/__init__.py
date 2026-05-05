"""SQLModel ORM models for the RBAC layer.

Importing this package registers every model on SQLModel.metadata so
Alembic autogenerate can see them.
"""

from db.models.api_key import ApiKey
from db.models.audit_log import AuditLog
from db.models.migration_status import MigrationStatus
from db.models.permission import Permission
from db.models.role import Role
from db.models.role_permission import RolePermission
from db.models.user import User
from db.models.user_preferences import UserPreferences
from db.models.user_role import UserRole

__all__ = [
    "ApiKey",
    "AuditLog",
    "MigrationStatus",
    "Permission",
    "Role",
    "RolePermission",
    "User",
    "UserPreferences",
    "UserRole",
]
