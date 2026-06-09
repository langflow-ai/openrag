"""Workspace-wide connector availability policy (admin Connectors Permission UI)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from connectors.registry import get_connector_classes
from db.repositories import WorkspaceConfigRepo

CONNECTOR_ACCESS_SECTION = "connector_access"

# Derived from the connector registry so new connector types are governable
# without touching this module.
CONNECTOR_TYPES: tuple[str, ...] = tuple(cls.CONNECTOR_TYPE for cls in get_connector_classes())

_BUCKET_CONNECTOR_TYPES = frozenset({"aws_s3", "ibm_cos"})


def governable_connector_types() -> tuple[str, ...]:
    """Types shown in admin Connectors Permission — independent of the live connectors list."""
    from config.settings import IBM_AUTH_ENABLED, is_cloud_context

    if is_cloud_context() and not IBM_AUTH_ENABLED:
        return tuple(t for t in CONNECTOR_TYPES if t not in _BUCKET_CONNECTOR_TYPES)
    return CONNECTOR_TYPES


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


def is_connector_access_policy_enforced() -> bool:
    """Workspace connector policy applies in SaaS/cloud context only."""
    from config.settings import is_cloud_context

    return is_cloud_context()


async def is_connector_allowed(session: AsyncSession, connector_type: str) -> bool:
    access = await get_access_map(session)
    return access.get(connector_type, True)


async def is_connector_allowed_for_request(
    session: AsyncSession,
    connector_type: str,
) -> bool:
    if not is_connector_access_policy_enforced():
        return True
    return await is_connector_allowed(session, connector_type)


def filter_connectors_for_user(
    connector_metadata: dict[str, dict],
    access_map: dict[str, bool],
) -> dict[str, dict]:
    """Apply workspace policy to the connector list for every role."""
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
    for connector_type in governable_connector_types():
        meta = connector_metadata.get(connector_type, {})
        items.append(
            {
                "type": connector_type,
                "name": str(meta.get("name", connector_type.replace("_", " ").title())),
                "enabled": access_map.get(connector_type, True),
            }
        )
    return items
