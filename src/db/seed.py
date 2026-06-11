"""Idempotent seed for built-in roles and permissions.

The full permission catalog and the role-permission default mapping live here.
To add a permission, role, or default role grant: edit this file only —
``seed_roles_and_permissions`` runs on application startup (after Alembic)
and backfills missing rows on existing installs.

To revoke a permission from a role on existing installs, add an explicit
Alembic data migration (see ``0006_revoke_provider_override_nonadmin``);
the seeder is additive-only and never removes rows.

Built-in role IDs are stable, deterministic strings so cross-environment
references (e.g. tests, docs) do not depend on UUIDs.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Permission, Role, RolePermission

# ---------------------------------------------------------------------------
# Permission catalog
# (resource, action, description)
# ---------------------------------------------------------------------------

PERMISSIONS: list[tuple[str, str, str]] = [
    # Infra
    ("config", "read", "Read workspace configuration"),
    ("config", "write", "Write workspace configuration"),
    ("providers", "read", "Read provider configuration"),
    ("providers", "write", "Write workspace provider configuration"),
    ("providers", "override:self", "Override providers in own user preferences"),
    ("opensearch", "admin", "Administer OpenSearch security"),
    # Users / RBAC
    ("users", "list", "List users"),
    ("users", "read", "Read user profile"),
    ("users", "invite", "Invite or update user records"),
    ("users", "delete", "Delete users"),
    ("roles", "list", "List roles"),
    ("roles", "assign", "Assign or revoke roles"),
    ("roles", "create", "Create custom roles"),
    ("roles", "edit", "Edit custom roles"),
    ("roles", "delete", "Delete custom roles"),
    ("audit", "read", "Read audit log"),
    # Connectors
    ("connectors", "list:own", "List own connectors"),
    ("connectors", "list:all", "List all connectors in the workspace"),
    ("connectors", "create", "Create connectors"),
    ("connectors", "delete:own", "Delete own connectors"),
    ("connectors", "delete:any", "Delete any connector"),
    ("connectors", "use", "Use connector OAuth and browse"),
    ("connectors", "manage:access", "Manage workspace connector availability"),
    # Knowledge
    ("knowledge", "upload", "Upload documents"),
    ("knowledge", "delete:own", "Delete own documents"),
    ("knowledge", "delete:any", "Delete any document"),
    ("knowledge", "read:own", "Read own documents"),
    ("knowledge", "read:all", "Read all documents"),
    ("kf", "create", "Create knowledge filters"),
    ("kf", "edit:own", "Edit own knowledge filters"),
    ("kf", "edit:any", "Edit any knowledge filter"),
    ("kf", "share", "Share knowledge filters"),
    # Chat / search
    ("chat", "use", "Use chat"),
    ("search", "use", "Use search"),
    ("conversations", "read:own", "Read own conversations"),
    ("conversations", "read:all", "Read all conversations"),
    ("conversations", "delete:own", "Delete own conversations"),
    ("conversations", "delete:any", "Delete any conversation"),
    # Flows / agent
    ("flows", "read", "Read flows"),
    ("flows", "edit", "Edit flows"),
    ("agent", "prompt:override", "Override agent system prompt for self"),
    ("agent", "prompt:global", "Edit global agent system prompt"),
    # API keys
    ("apikeys", "create:self", "Create own API keys"),
    ("apikeys", "revoke:self", "Revoke own API keys"),
    ("apikeys", "revoke:any", "Revoke any API key"),
    ("apikeys", "list:any", "List API keys for any user"),
]


def permission_name(resource: str, action: str) -> str:
    return f"{resource}:{action}"


# ---------------------------------------------------------------------------
# Built-in roles + role/permission mapping
# ---------------------------------------------------------------------------

BUILTIN_ROLES: list[tuple[str, str, str]] = [
    # (id, name, description)
    ("role-admin", "admin", "Full control over infra, users, and all data."),
    (
        "role-developer",
        "developer",
        "Manages own connectors, flows, and ingestion. No infra writes.",
    ),
    ("role-user", "user", "Default end-user. Chat, search, and own connectors."),
    ("role-viewer", "viewer", "Read-only chat and search."),
]


def _admin_perms() -> set[str]:
    return {permission_name(r, a) for r, a, _ in PERMISSIONS}


def _developer_perms() -> set[str]:
    return {
        # NOTE: providers are admin-only — no provider perms for developers.
        "connectors:list:own",
        "connectors:create",
        "connectors:delete:own",
        "connectors:use",
        "knowledge:upload",
        "knowledge:delete:own",
        "knowledge:read:own",
        "kf:create",
        "kf:edit:own",
        "chat:use",
        "search:use",
        "conversations:read:own",
        "conversations:delete:own",
        "flows:read",
        "flows:edit",
        "agent:prompt:override",
        "apikeys:create:self",
        "apikeys:revoke:self",
    }


def _user_perms() -> set[str]:
    return {
        # NOTE: providers are admin-only — no provider perms for users.
        "connectors:list:own",
        "connectors:create",
        "connectors:delete:own",
        "connectors:use",
        "knowledge:upload",
        "knowledge:delete:own",
        "knowledge:read:own",
        "kf:create",
        "kf:edit:own",
        "chat:use",
        "search:use",
        "conversations:read:own",
        "conversations:delete:own",
        "flows:read",
        "agent:prompt:override",
        "apikeys:create:self",
        "apikeys:revoke:self",
    }


def _viewer_perms() -> set[str]:
    return {
        "chat:use",
        "search:use",
        "conversations:read:own",
        "conversations:delete:own",
        "flows:read",
    }


ROLE_PERMISSION_MAP: dict[str, set[str]] = {
    "admin": _admin_perms(),
    "developer": _developer_perms(),
    "user": _user_perms(),
    "viewer": _viewer_perms(),
}


# ---------------------------------------------------------------------------
# Idempotent seeder
# ---------------------------------------------------------------------------


async def seed_roles_and_permissions(session: AsyncSession) -> None:
    """Insert any missing roles/permissions/role_permissions. Safe to call repeatedly.

    Alembic ``0002`` bootstraps greenfield installs; startup and tests call
    this for additive catalog sync. Does not commit — caller commits.
    """

    # Permissions
    existing_perms = {
        p.name: p for p in (await session.execute(select(Permission))).scalars().all()
    }
    perm_id_by_name: dict[str, str] = {p.name: p.id for p in existing_perms.values()}

    for resource, action, description in PERMISSIONS:
        name = permission_name(resource, action)
        if name in existing_perms:
            continue
        pid = str(uuid.uuid4())
        session.add(
            Permission(
                id=pid,
                name=name,
                resource=resource,
                action=action,
                description=description,
            )
        )
        perm_id_by_name[name] = pid
    await session.flush()

    # Roles
    existing_roles = {r.name: r for r in (await session.execute(select(Role))).scalars().all()}
    for role_id, role_name, description in BUILTIN_ROLES:
        if role_name in existing_roles:
            continue
        session.add(
            Role(
                id=role_id,
                name=role_name,
                description=description,
                is_system=True,
            )
        )
    await session.flush()

    # Re-fetch so we have IDs for the just-inserted rows.
    role_id_by_name = {r.name: r.id for r in (await session.execute(select(Role))).scalars().all()}

    # Role permissions (additive only — never remove perms set by an admin via UI)
    existing_rp = set(
        (rp.role_id, rp.permission_id)
        for rp in (await session.execute(select(RolePermission))).scalars().all()
    )

    for role_name, perm_names in ROLE_PERMISSION_MAP.items():
        rid = role_id_by_name.get(role_name)
        if rid is None:
            continue
        for pname in perm_names:
            pid = perm_id_by_name.get(pname)
            if pid is None:
                continue
            if (rid, pid) in existing_rp:
                continue
            session.add(RolePermission(role_id=rid, permission_id=pid))

    await session.flush()
