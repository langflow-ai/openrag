"""Sync DB user roles when OPENRAG_DEFAULT_ROLE / OPENRAG_NOAUTH_ROLE change.

Opt-in via ``OPENRAG_SYNC_DEFAULT_ROLE=true``. OSS run mode only
(``OPENRAG_RUN_MODE=oss``). Run manually via ``scripts/sync_default_user_roles.py``.

Only users with *exactly one* role matching the previously recorded env
default are updated. Users with multiple roles or a manually changed
single role are left untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import (
    get_default_user_role,
    get_noauth_user_role,
    is_default_role_sync_enabled,
)
from db.repositories import AuditRepo, RoleRepo, UserRepo
from db.repositories.workspace_config_repo import WorkspaceConfigRepo
from utils.logging_config import get_logger

logger = get_logger(__name__)

META_SECTION = "meta"
SYNC_STATE_KEY = "rbac_default_role_sync"
PAGE_SIZE = 100
# Code defaults when no baseline exists yet (matches user_service / settings).
IMPLICIT_DEFAULT_USER_ROLE = "user"
IMPLICIT_DEFAULT_NOAUTH_ROLE = "admin"


@dataclass
class DefaultRoleSyncResult:
    enabled: bool
    dry_run: bool
    baseline_recorded: bool = False
    default_role_changed: bool = False
    noauth_role_changed: bool = False
    updated_users: int = 0
    skipped_users: int = 0
    stale_users: int = 0
    old_default_role: str | None = None
    new_default_role: str = ""
    old_noauth_role: str | None = None
    new_noauth_role: str = ""
    changes: list[dict[str, str]] = field(default_factory=list)

    def as_log_kwargs(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "dry_run": self.dry_run,
            "baseline_recorded": self.baseline_recorded,
            "default_role_changed": self.default_role_changed,
            "noauth_role_changed": self.noauth_role_changed,
            "updated_users": self.updated_users,
            "skipped_users": self.skipped_users,
            "stale_users": self.stale_users,
            "old_default_role": self.old_default_role,
            "new_default_role": self.new_default_role,
            "old_noauth_role": self.old_noauth_role,
            "new_noauth_role": self.new_noauth_role,
            "change_count": len(self.changes),
        }


def _read_sync_state(meta: dict[str, Any]) -> dict[str, str | None]:
    state = meta.get(SYNC_STATE_KEY) or {}
    return {
        "default_role": state.get("default_role"),
        "noauth_role": state.get("noauth_role"),
    }


async def _write_sync_state(
    repo: WorkspaceConfigRepo,
    *,
    default_role: str,
    noauth_role: str,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    meta = await repo.get_section(META_SECTION) or {}
    meta = dict(meta)
    meta[SYNC_STATE_KEY] = {
        "default_role": default_role,
        "noauth_role": noauth_role,
    }
    await repo.upsert(META_SECTION, meta)


def _is_noauth_user(user) -> bool:
    return user.oauth_subject == "anonymous"


async def _count_stale_default_users(
    session: AsyncSession,
    *,
    expected_role: str,
) -> int:
    """Users with a single role that differs from the current env default."""
    role_repo = RoleRepo(session)
    user_repo = UserRepo(session)
    stale = 0
    offset = 0
    while True:
        users = await user_repo.list_all(limit=PAGE_SIZE, offset=offset)
        if not users:
            break
        for user in users:
            if _is_noauth_user(user):
                continue
            roles = await role_repo.list_user_roles(user.id)
            if len(roles) == 1 and roles[0].name != expected_role:
                stale += 1
        offset += PAGE_SIZE
    return stale


async def sync_default_roles_if_changed(
    session: AsyncSession,
    *,
    dry_run: bool = False,
    force_baseline: bool = False,
    from_role: str | None = None,
    from_noauth_role: str | None = None,
    to_role: str | None = None,
    to_noauth_role: str | None = None,
    enabled: bool | None = None,
) -> DefaultRoleSyncResult:
    """Apply env default-role changes to eligible existing users.

    When ``force_baseline`` is true, record the current env values without
    mutating any user rows (useful after enabling the flag on an existing DB).

    ``from_role`` / ``from_noauth_role`` override the stored baseline for one
    run — use when the baseline was recorded before users were migrated
    (e.g. baseline and env are both ``admin`` but users still have ``user``).

    ``to_role`` / ``to_noauth_role`` override ``OPENRAG_DEFAULT_ROLE`` /
    ``OPENRAG_NOAUTH_ROLE`` for this run when set explicitly on the CLI.
    """
    flag_enabled = is_default_role_sync_enabled() if enabled is None else enabled
    new_default = to_role if to_role is not None else get_default_user_role()
    new_noauth = to_noauth_role if to_noauth_role is not None else get_noauth_user_role()

    result = DefaultRoleSyncResult(
        enabled=flag_enabled,
        dry_run=dry_run,
        new_default_role=new_default,
        new_noauth_role=new_noauth,
    )

    if not flag_enabled:
        logger.debug("Default role sync skipped — OPENRAG_SYNC_DEFAULT_ROLE is off")
        return result

    config_repo = WorkspaceConfigRepo(session)
    meta = await config_repo.get_section(META_SECTION) or {}
    state = _read_sync_state(meta)
    stored_default = state["default_role"]
    stored_noauth = state["noauth_role"]

    if force_baseline:
        await _write_sync_state(
            config_repo,
            default_role=new_default,
            noauth_role=new_noauth,
            dry_run=dry_run,
        )
        result.baseline_recorded = True
        logger.info(
            "Recorded RBAC default-role baseline",
            default_role=new_default,
            noauth_role=new_noauth,
            dry_run=dry_run,
        )
        return result

    if from_role is not None:
        old_default = from_role
    elif stored_default is not None:
        old_default = stored_default
    else:
        old_default = IMPLICIT_DEFAULT_USER_ROLE
        result.baseline_recorded = True

    if from_noauth_role is not None:
        old_noauth = from_noauth_role
    elif stored_noauth is not None:
        old_noauth = stored_noauth
    else:
        old_noauth = IMPLICIT_DEFAULT_NOAUTH_ROLE
        result.baseline_recorded = True

    result.old_default_role = old_default
    result.old_noauth_role = old_noauth

    result.default_role_changed = old_default != new_default
    result.noauth_role_changed = old_noauth != new_noauth
    if not result.default_role_changed and not result.noauth_role_changed:
        result.stale_users = await _count_stale_default_users(session, expected_role=new_default)
        if stored_default is None or stored_noauth is None:
            await _write_sync_state(
                config_repo,
                default_role=new_default,
                noauth_role=new_noauth,
                dry_run=dry_run,
            )
            result.baseline_recorded = True
        logger.debug(
            "Default role sync: env defaults unchanged",
            stale_users=result.stale_users,
        )
        return result

    role_repo = RoleRepo(session)
    user_repo = UserRepo(session)
    audit_repo = AuditRepo(session)

    default_role_row = await role_repo.get_by_name(new_default)
    noauth_role_row = await role_repo.get_by_name(new_noauth)
    if result.default_role_changed and default_role_row is None:
        logger.warning(
            "Default role sync: target default role not found in DB",
            role_name=new_default,
        )
    if result.noauth_role_changed and noauth_role_row is None:
        logger.warning(
            "Default role sync: target no-auth role not found in DB",
            role_name=new_noauth,
        )

    offset = 0
    while True:
        users = await user_repo.list_all(limit=PAGE_SIZE, offset=offset)
        if not users:
            break

        for user in users:
            is_noauth = _is_noauth_user(user)
            if is_noauth:
                if not result.noauth_role_changed:
                    continue
                old_role_name = old_noauth
                new_role_name = new_noauth
                target_role = noauth_role_row
            else:
                if not result.default_role_changed:
                    continue
                old_role_name = old_default
                new_role_name = new_default
                target_role = default_role_row

            if not old_role_name or old_role_name == new_role_name or target_role is None:
                result.skipped_users += 1
                continue

            roles = await role_repo.list_user_roles(user.id)
            if len(roles) != 1 or roles[0].name != old_role_name:
                result.skipped_users += 1
                continue

            change = {
                "user_id": user.id,
                "oauth_provider": user.oauth_provider or "",
                "oauth_subject": user.oauth_subject or "",
                "from_role": old_role_name,
                "to_role": new_role_name,
            }
            result.changes.append(change)

            if dry_run:
                result.updated_users += 1
                continue

            await role_repo.revoke_role(user.id, roles[0].id)
            await role_repo.assign_role(user.id, target_role.id)
            await audit_repo.write(
                event="user.roles_synced",
                actor_user_id=None,
                target_type="user",
                target_id=user.id,
                audit_metadata={
                    "added": [new_role_name],
                    "removed": [old_role_name],
                    "source": "default_role_env_sync",
                },
            )
            result.updated_users += 1

        offset += PAGE_SIZE

    await _write_sync_state(
        config_repo,
        default_role=new_default,
        noauth_role=new_noauth,
        dry_run=dry_run,
    )

    logger.info("Default role sync finished", **result.as_log_kwargs())
    return result
