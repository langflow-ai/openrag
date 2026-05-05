"""RBAC chokepoint.

Every permission decision in OpenRAG goes through `RBACService.has_permission`
or `RBACService.get_user_permissions`. Keeping a single class here is what
makes a future swap to Casbin / OpenFGA / SpiceDB a one-class refactor
rather than a sweep across every route handler.

Permissions are cached per-process for `OPENRAG_PERM_CACHE_TTL` seconds
(default 60). Cache invalidates explicitly on role/permission mutations.
"""

from __future__ import annotations

import os
from typing import Optional

from cachetools import TTLCache
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories import AuditRepo, RoleRepo
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _cache_ttl() -> int:
    try:
        return int(os.getenv("OPENRAG_PERM_CACHE_TTL", "60"))
    except ValueError:
        return 60


class RBACService:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        self._cache: TTLCache[str, frozenset[str]] = TTLCache(
            maxsize=1024, ttl=_cache_ttl()
        )

    # ---------------- public API ---------------------------------------

    async def get_user_permissions(
        self,
        user_id: str,
        role_override: Optional[list[str]] = None,
    ) -> set[str]:
        """Resolve the permission set for a user.

        If `role_override` is provided (e.g. via API key snapshot), it
        replaces the user's live role membership and bypasses the cache.
        """
        if role_override is not None:
            async with self._session_factory() as session:
                role_repo = RoleRepo(session)
                return await role_repo.list_permissions_for_role_ids(role_override)

        cached = self._cache.get(user_id)
        if cached is not None:
            return set(cached)

        async with self._session_factory() as session:
            role_repo = RoleRepo(session)
            perms = await role_repo.list_permissions_for_user(user_id)

        self._cache[user_id] = frozenset(perms)
        return perms

    async def has_permission(
        self,
        user_id: str,
        perm: str,
        role_override: Optional[list[str]] = None,
    ) -> bool:
        return perm in await self.get_user_permissions(user_id, role_override)

    async def assert_owner_or_perm(
        self,
        user: User,
        owner_id: Optional[str],
        owned_perm: str,
        any_perm: str,
        role_override: Optional[list[str]] = None,
    ) -> None:
        """Self-or-elevated check used by /delete:own etc. Raises 403 on miss."""
        perms = await self.get_user_permissions(user.user_id, role_override)
        if any_perm in perms:
            return
        if owner_id == user.user_id and owned_perm in perms:
            return
        await self.audit_denied(user.user_id, f"({owned_perm}|{any_perm})")
        raise HTTPException(
            status_code=403,
            detail={"error": "permission_denied", "required": [owned_perm, any_perm]},
        )

    async def audit_denied(self, user_id: Optional[str], required: str) -> None:
        try:
            async with self._session_factory() as session:
                audit = AuditRepo(session)
                await audit.write(
                    event="permission.denied",
                    actor_user_id=user_id,
                    audit_metadata={"required": required},
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            # Audit failure must never break the request flow.
            logger.warning("audit_denied write failed", error=str(exc))

    def invalidate(self, user_id: str) -> None:
        self._cache.pop(user_id, None)

    def invalidate_all(self) -> None:
        self._cache.clear()
