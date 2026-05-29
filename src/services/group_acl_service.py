"""Resolve connector-backed group ACL roles and principals."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


class GroupACLService:
    """Collect current-user group roles from pluggable connectors."""

    def __init__(self, connector_service: Any, cache_ttl_seconds: int | None = None):
        self.connector_service = connector_service
        if cache_ttl_seconds is None:
            from config.settings import GROUP_ACL_CACHE_TTL_SECONDS

            cache_ttl_seconds = GROUP_ACL_CACHE_TTL_SECONDS
        self.cache_ttl_seconds = max(cache_ttl_seconds, 0)
        self._cache: dict[str, tuple[float, list[str]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get_user_group_roles(self, user: User | None) -> list[str]:
        """Return OpenSearch backend roles for the user's upstream groups."""
        if user is None or not user.user_id:
            return []

        if self.cache_ttl_seconds <= 0:
            return await self._resolve_user_group_roles(user)

        if self.cache_ttl_seconds > 0:
            cached = self._cache.get(user.user_id)
            now = time.monotonic()
            if cached and cached[0] > now:
                return list(cached[1])

        lock = self._locks.setdefault(user.user_id, asyncio.Lock())
        async with lock:
            if self.cache_ttl_seconds > 0:
                cached = self._cache.get(user.user_id)
                now = time.monotonic()
                if cached and cached[0] > now:
                    return list(cached[1])

            roles = await self._resolve_user_group_roles(user)
            if self.cache_ttl_seconds > 0:
                self._cache[user.user_id] = (
                    time.monotonic() + self.cache_ttl_seconds,
                    list(roles),
                )
            return roles

    def invalidate_user(self, user_id: str) -> None:
        self._cache.pop(user_id, None)
        self._locks.pop(user_id, None)

    def clear(self) -> None:
        self._cache.clear()
        self._locks.clear()

    async def _resolve_user_group_roles(self, user: User) -> list[str]:
        connection_manager = getattr(self.connector_service, "connection_manager", None)
        if connection_manager is None:
            return []

        try:
            connections = await connection_manager.list_connections(user_id=user.user_id)
        except Exception as e:
            logger.warning("Failed to list connector connections for group ACLs", error=str(e))
            return []

        roles: list[str] = []
        seen: set[str] = set()
        for connection in connections:
            if not getattr(connection, "is_active", False):
                continue

            connector = None
            try:
                connector = await self.connector_service.get_connector(connection.connection_id)
            except Exception as e:
                logger.debug(
                    "Skipping connector group ACL lookup",
                    connection_id=getattr(connection, "connection_id", None),
                    connector_type=getattr(connection, "connector_type", None),
                    error=str(e),
                )
                continue

            if connector is None:
                continue

            try:
                connector_roles = await connector.get_current_user_group_roles()
            except NotImplementedError:
                continue
            except Exception as e:
                logger.warning(
                    "Connector group ACL lookup failed",
                    connection_id=getattr(connection, "connection_id", None),
                    connector_type=getattr(connection, "connector_type", None),
                    error=str(e),
                )
                continue

            for role in connector_roles or []:
                role = str(role).strip()
                if role and role not in seen:
                    seen.add(role)
                    roles.append(role)

        return roles
