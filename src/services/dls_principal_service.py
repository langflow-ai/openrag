"""Maintain OpenSearch DLS lookup rows for connector ACL principals."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from session_manager import User
from utils.group_acl import (
    acl_principal_label,
    unique_acl_principal_labels,
    unique_acl_principals,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)


class DLSPrincipalService:
    """Refresh the per-OpenSearch-user principal lookup index.

    Document DLS can only see the OpenSearch authenticated principal and roles.
    This service bridges connector-specific user aliases by writing a lookup row
    keyed by the actual OpenSearch user name. DLS then uses a terms lookup on the
    row's ``principals`` array.
    """

    def __init__(
        self,
        connector_service: Any,
        opensearch_client: Any | None = None,
        refresh_ttl_seconds: int | None = None,
    ):
        self.connector_service = connector_service
        self.opensearch_client = opensearch_client
        if refresh_ttl_seconds is None:
            from config.settings import DLS_PRINCIPAL_REFRESH_TTL_SECONDS

            refresh_ttl_seconds = DLS_PRINCIPAL_REFRESH_TTL_SECONDS
        self.refresh_ttl_seconds = max(refresh_ttl_seconds, 0)
        self._admin_opensearch_client: Any | None = None
        self._ensure_lock = asyncio.Lock()
        self._index_checked = False
        self._cache: dict[str, tuple[float, list[str]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def refresh_user_principals(
        self,
        user: User | None,
        *,
        group_roles: list[str] | None = None,
    ) -> list[str]:
        """Resolve and persist current DLS principals for this request user."""
        if user is None or not user.user_id:
            return []

        if self.refresh_ttl_seconds <= 0:
            return await self._refresh_user_principals_uncached(user, group_roles=group_roles)

        cache_key = self._refresh_cache_key(user, group_roles)
        if self.refresh_ttl_seconds > 0:
            cached = self._cache.get(cache_key)
            now = time.monotonic()
            if cached and cached[0] > now:
                return list(cached[1])

        lock = self._locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            if self.refresh_ttl_seconds > 0:
                cached = self._cache.get(cache_key)
                now = time.monotonic()
                if cached and cached[0] > now:
                    return list(cached[1])

            return await self._refresh_user_principals_uncached(user, group_roles=group_roles)

    async def _refresh_user_principals_uncached(
        self,
        user: User,
        *,
        group_roles: list[str] | None,
    ) -> list[str]:
        user_names = self._opensearch_user_names(user)
        if not user_names:
            return []

        client = self._get_opensearch_client()
        if client is None:
            logger.warning(
                "Unable to refresh DLS principals: OpenSearch client is unavailable",
                user_id=user.user_id,
            )
            return []

        try:
            await self.ensure_index(client)
        except Exception as e:
            logger.warning(
                "Failed to prepare DLS principal lookup index",
                user_id=user.user_id,
                user_names=user_names,
                error=str(e),
            )
            return []

        (
            connector_principals,
            connector_labels,
        ) = await self._resolve_connector_principals_and_labels(
            user,
            include_group_roles=group_roles is None,
        )
        auth_principals = self._resolve_auth_user_principals(user)
        principals = unique_acl_principals(
            [
                *(group_roles or []),
                *connector_principals,
                *auth_principals,
            ]
        )
        principal_labels = unique_acl_principal_labels(
            [
                *connector_labels,
                *self._labels_for_group_roles(group_roles or []),
                *self._labels_for_auth_user_principals(user, auth_principals),
            ]
        )

        try:
            updated_at = datetime.now(UTC).isoformat()
            for user_name in user_names:
                await client.index(
                    index=self.index_name,
                    id=user_name,
                    body={
                        "user_name": user_name,
                        "auth_user_id": user.user_id,
                        "auth_email": user.email,
                        "provider": user.provider,
                        "principals": principals,
                        "principal_labels": principal_labels,
                        "updated_at": updated_at,
                    },
                    refresh="wait_for",
                )
            self._cache_principals(user, group_roles, principals)
        except Exception as e:
            logger.warning(
                "Failed to refresh DLS principal lookup row",
                user_id=user.user_id,
                user_names=user_names,
                principal_count=len(principals),
                error=str(e),
            )

        return principals

    def invalidate_user(self, user: User | str) -> None:
        """Drop cached DLS principals for one auth user or OpenSearch user name."""
        user_id = user.user_id if isinstance(user, User) else user
        keys = [key for key in self._cache if user_id in key.split("\x1f")]
        for key in keys:
            self._cache.pop(key, None)
            self._locks.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()
        self._locks.clear()

    def _cache_principals(
        self,
        user: User,
        group_roles: list[str] | None,
        principals: list[str],
    ) -> None:
        if self.refresh_ttl_seconds <= 0:
            return
        self._cache[self._refresh_cache_key(user, group_roles)] = (
            time.monotonic() + self.refresh_ttl_seconds,
            list(principals),
        )

    def _refresh_cache_key(self, user: User, group_roles: list[str] | None) -> str:
        key_parts = [
            user.user_id,
            user.opensearch_username,
            user.email,
            user.provider,
        ]
        if group_roles is not None:
            key_parts.extend(sorted(group_roles))
        return "\x1f".join(str(part) for part in key_parts if part)

    @property
    def index_name(self) -> str:
        from config.settings import DLS_PRINCIPAL_INDEX_NAME

        return DLS_PRINCIPAL_INDEX_NAME

    async def ensure_index(self, client: Any) -> None:
        """Create the lookup index if it does not exist."""
        if self._index_checked:
            return

        async with self._ensure_lock:
            if self._index_checked:
                return

            from config.settings import DLS_PRINCIPAL_INDEX_BODY

            if not await client.indices.exists(index=self.index_name):
                await client.indices.create(index=self.index_name, body=DLS_PRINCIPAL_INDEX_BODY)
                logger.info("Created DLS principal lookup index", index_name=self.index_name)
            else:
                try:
                    mapping = await client.indices.get_mapping(index=self.index_name)
                    properties = (
                        mapping.get(self.index_name, {}).get("mappings", {}).get("properties", {})
                    )
                    if properties.get("principal_labels") is None:
                        await client.indices.put_mapping(
                            index=self.index_name,
                            body={
                                "properties": {
                                    "principal_labels": DLS_PRINCIPAL_INDEX_BODY["mappings"][
                                        "properties"
                                    ]["principal_labels"]
                                }
                            },
                        )
                except AttributeError:
                    logger.debug(
                        "Skipping DLS principal label mapping backfill; client does not expose mapping APIs",
                        index_name=self.index_name,
                    )
            self._index_checked = True

    def _get_opensearch_client(self) -> Any | None:
        # An explicitly injected client wins; otherwise build (once) an
        # admin-identity client using the same run-mode switching as the
        # startup security bootstrap (app/lifespan.py) and onboarding
        # (api/settings/endpoints.py): SaaS -> platform service-token JWT;
        # on-prem/OSS -> OpenSearch basic auth.
        if self.opensearch_client is not None:
            return self.opensearch_client
        if self._admin_opensearch_client is not None:
            return self._admin_opensearch_client

        try:
            from config.settings import (
                clients,
                get_openrag_service_token,
                get_opensearch_password,
                get_opensearch_username,
            )
            from utils.run_mode_utils import (
                is_run_mode_on_prem,
                is_run_mode_saas,
            )

            if is_run_mode_saas():
                service_token = get_openrag_service_token()
                if not service_token:
                    logger.warning(
                        "DLS principal OpenSearch client unavailable: saas mode "
                        "but OPENRAG_SERVICE_TOKEN is not set"
                    )
                    return None
                self._admin_opensearch_client = clients.create_opensearch_client_from_jwt(
                    service_token
                )
                logger.info("DLS principal service: saas mode, using platform service token")
            else:
                mode = "on_prem" if is_run_mode_on_prem() else "oss"
                username = get_opensearch_username()
                password = get_opensearch_password()
                if not password:
                    logger.warning(
                        "DLS principal OpenSearch client unavailable: "
                        f"{mode} mode but OpenSearch password is not set"
                    )
                    return None
                self._admin_opensearch_client = clients.create_basic_opensearch_client(
                    username,
                    password,
                )
                logger.info(
                    f"DLS principal service: {mode} mode, using OpenSearch basic auth",
                    admin_username=username,
                )

            return self._admin_opensearch_client
        except Exception as e:
            logger.warning(
                "Failed to build DLS principal OpenSearch client",
                error=str(e),
            )
            return None

    @staticmethod
    def _opensearch_user_names(user: User) -> list[str]:
        return unique_acl_principals(
            [
                user.opensearch_username,
                user.user_id,
            ]
        )

    def _resolve_auth_user_principals(self, user: User) -> list[str]:
        connection_manager = getattr(self.connector_service, "connection_manager", None)
        resolver = getattr(connection_manager, "get_auth_user_principals", None)
        if resolver is None:
            return []
        try:
            return resolver(user) or []
        except Exception as e:
            logger.warning(
                "Failed to resolve auth-user DLS principals",
                user_id=user.user_id,
                error=str(e),
            )
            return []

    async def _resolve_connector_principals_and_labels(
        self,
        user: User,
        *,
        include_group_roles: bool,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        connection_manager = getattr(self.connector_service, "connection_manager", None)
        if connection_manager is None:
            return [], []

        try:
            connections = await connection_manager.list_connections(user_id=user.user_id)
        except Exception as e:
            logger.warning("Failed to list connector connections for DLS principals", error=str(e))
            return [], []

        principals: list[str] = []
        labels: list[dict[str, Any]] = []
        for connection in connections:
            if not getattr(connection, "is_active", False):
                continue

            try:
                connector = await self.connector_service.get_connector(connection.connection_id)
            except Exception as e:
                logger.debug(
                    "Skipping connector DLS principal lookup",
                    connection_id=getattr(connection, "connection_id", None),
                    connector_type=getattr(connection, "connector_type", None),
                    error=str(e),
                )
                continue

            if connector is None:
                continue

            label_resolver = getattr(connector, "get_current_user_principal_labels", None)
            if label_resolver is not None:
                try:
                    labels.extend(await label_resolver() or [])
                except NotImplementedError:
                    pass
                except Exception as e:
                    logger.warning(
                        "Connector DLS principal label lookup failed",
                        connection_id=getattr(connection, "connection_id", None),
                        connector_type=getattr(connection, "connector_type", None),
                        error=str(e),
                    )

            try:
                principals.extend(await connector.get_current_user_principals() or [])
            except NotImplementedError:
                pass
            except Exception as e:
                logger.warning(
                    "Connector DLS principal lookup failed",
                    connection_id=getattr(connection, "connection_id", None),
                    connector_type=getattr(connection, "connector_type", None),
                    error=str(e),
                )

            if not include_group_roles:
                continue

            try:
                principals.extend(await connector.get_current_user_group_roles() or [])
            except NotImplementedError:
                pass
            except Exception as e:
                logger.warning(
                    "Connector group principal lookup failed",
                    connection_id=getattr(connection, "connection_id", None),
                    connector_type=getattr(connection, "connector_type", None),
                    error=str(e),
                )

        return principals, labels

    @staticmethod
    def _principal_label_kind(principal: str) -> str:
        if principal.startswith("g:"):
            return "group"
        if principal.startswith("u:"):
            return "user"
        return "unknown"

    @staticmethod
    def _principal_label_provider(principal: str) -> str:
        parts = principal.split(":", 2)
        return parts[1] if len(parts) > 1 and parts[1] else "unknown"

    def _labels_for_group_roles(self, group_roles: list[str]) -> list[dict[str, Any]]:
        labels: list[dict[str, Any]] = []
        for role in group_roles:
            label = acl_principal_label(
                role,
                kind="group",
                provider=self._principal_label_provider(role),
                display_name=role,
                external_id=role,
            )
            if label:
                labels.append(label)
        return labels

    def _labels_for_auth_user_principals(
        self,
        user: User,
        auth_principals: list[str],
    ) -> list[dict[str, Any]]:
        labels: list[dict[str, Any]] = []
        for principal in auth_principals:
            label = acl_principal_label(
                principal,
                kind=self._principal_label_kind(principal),
                provider=self._principal_label_provider(principal),
                display_name=user.name or user.email or principal,
                email=user.email,
                external_id=user.user_id,
            )
            if label:
                labels.append(label)
        return labels
