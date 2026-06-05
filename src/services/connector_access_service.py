"""Persist which connectors non-admin users may use (admin settings UI)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from connectors.connection_manager import CONNECTOR_TYPE_KEYS
from db.repositories import WorkspaceConfigRepo
from session_manager import User

CONNECTOR_ACCESS_SECTION = "connector_access"

# Derived from the connector registry so new connector types are governable
# without touching this module.
CONNECTOR_TYPES: tuple[str, ...] = CONNECTOR_TYPE_KEYS


async def get_access_map(session: AsyncSession) -> dict[str, bool]:
    stored = await WorkspaceConfigRepo(session).get_section(CONNECTOR_ACCESS_SECTION) or {}
    return {
        connector_type: bool(stored.get(connector_type, True)) for connector_type in CONNECTOR_TYPES
    }


async def set_connector_access_bulk(
    session: AsyncSession,
    access: dict[str, bool],
    actor_user_id: str | None,
) -> dict[str, bool]:
    current = await get_access_map(session)
    for connector_type, enabled in access.items():
        if connector_type not in CONNECTOR_TYPES:
            raise ValueError(f"Unknown connector type: {connector_type}")
        current[connector_type] = enabled
    repo = WorkspaceConfigRepo(session)
    await repo.upsert(CONNECTOR_ACCESS_SECTION, current, actor_user_id=actor_user_id)
    return current


async def user_is_admin(session: AsyncSession, user: User) -> bool:
    from db.repositories import RoleRepo, UserRepo

    user_repo = UserRepo(session)
    db_user = await user_repo.get_by_oauth(user.provider or "unknown", user.user_id)
    if db_user is None:
        db_user = await user_repo.get_by_id(user.user_id)
    if db_user is None:
        return False
    roles = await RoleRepo(session).list_user_roles(db_user.id)
    return any(role.name == "admin" for role in roles)


async def is_connector_allowed(session: AsyncSession, connector_type: str) -> bool:
    access = await get_access_map(session)
    return access.get(connector_type, True)


def filter_connectors_for_user(
    connector_metadata: dict[str, dict],
    access_map: dict[str, bool],
    *,
    is_admin: bool,
) -> dict[str, dict]:
    if is_admin:
        return connector_metadata
    return {
        connector_type: meta
        for connector_type, meta in connector_metadata.items()
        if access_map.get(connector_type, True)
    }


async def list_access_for_admin(
    session: AsyncSession,
    connector_metadata: dict[str, dict],
) -> list[dict[str, str | bool]]:
    access_map = await get_access_map(session)
    items: list[dict[str, str | bool]] = []
    for connector_type in CONNECTOR_TYPES:
        meta = connector_metadata.get(connector_type, {})
        items.append(
            {
                "type": connector_type,
                "name": str(meta.get("name", connector_type.replace("_", " ").title())),
                "enabled": access_map.get(connector_type, True),
            }
        )
    return items
