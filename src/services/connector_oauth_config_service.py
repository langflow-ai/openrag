"""Workspace-level OAuth client credential overrides for OAuth-kind connectors.

Lets an admin override the env-var-configured OAuth client id/secret per
credential key (e.g. "google_drive", "microsoft_graph" — the latter shared
by OneDrive + SharePoint, see BaseConnector.OAUTH_CREDENTIAL_KEY) from the
UI. Falls back to the connector's env var when no override is stored.

Resolution happens from synchronous, session-less contexts
(BaseConnector.__init__, is_available()), so overrides are kept in a
per-process in-memory cache, warmed once at startup (warm_cache) and
updated synchronously whenever an admin saves/clears credentials. This
mirrors the existing per-process RBAC/OAuth caches — the app already
hard-requires a single uvicorn worker for the same reason, so no
cross-worker staleness is possible.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import is_workspace_oauth_overrides_enabled
from connectors.registry import get_connector_classes
from db.repositories import WorkspaceConfigRepo
from utils.encryption import decrypt_secret, encrypt_secret
from utils.logging_config import get_logger

logger = get_logger(__name__)

OAUTH_CONFIG_SECTION = "connector_oauth_config"

# {credential_key: {"client_id": str | None, "client_secret": str | None}}
# None until warm_cache() runs — treated as "no override" so early-boot
# credential lookups degrade gracefully to env-var-only behavior.
_CACHE: dict[str, dict[str, str | None]] | None = None


def credential_keys() -> frozenset[str]:
    """OAuth-kind connector credential keys, derived from the registry."""
    return frozenset(
        cls.OAUTH_CREDENTIAL_KEY or cls.CONNECTOR_TYPE
        for cls in get_connector_classes()
        if cls.CONNECTOR_KIND == "oauth"
    )


def _representative_connector_class(credential_key: str):
    """Any OAuth-kind connector class sharing this credential key (for its env var names)."""
    for cls in get_connector_classes():
        if cls.CONNECTOR_KIND != "oauth":
            continue
        if (cls.OAUTH_CREDENTIAL_KEY or cls.CONNECTOR_TYPE) == credential_key:
            return cls
    return None


async def warm_cache(session_factory) -> None:
    """Load and decrypt all stored overrides into the in-process cache. Call once at startup."""
    global _CACHE
    if not is_workspace_oauth_overrides_enabled():
        _CACHE = {}
        return
    try:
        async with session_factory() as session:
            stored = await WorkspaceConfigRepo(session).get_section(OAUTH_CONFIG_SECTION) or {}
    except Exception:
        logger.exception("Failed to warm connector OAuth config cache")
        _CACHE = {}
        return

    cache: dict[str, dict[str, str | None]] = {}
    for key, entry in stored.items():
        client_id = entry.get("client_id")
        secret_payload = entry.get("client_secret")
        client_secret = None
        if secret_payload:
            try:
                client_secret = decrypt_secret(secret_payload)
            except Exception:
                logger.error("Failed to decrypt stored OAuth client secret", credential_key=key)
        cache[key] = {"client_id": client_id, "client_secret": client_secret}
    _CACHE = cache
    logger.info("Warmed connector OAuth config cache", keys=list(cache.keys()))


def get_cached_client_id(credential_key: str) -> str | None:
    if _CACHE is None or not is_workspace_oauth_overrides_enabled():
        return None
    return _CACHE.get(credential_key, {}).get("client_id")


def get_cached_client_secret(credential_key: str) -> str | None:
    if _CACHE is None or not is_workspace_oauth_overrides_enabled():
        return None
    return _CACHE.get(credential_key, {}).get("client_secret")


def _set_cache_entry(credential_key: str, client_id: str | None, client_secret: str | None) -> None:
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
    _CACHE[credential_key] = {"client_id": client_id, "client_secret": client_secret}


def _clear_cache_entry(credential_key: str) -> None:
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
    _CACHE.pop(credential_key, None)


async def get_oauth_config_status(session: AsyncSession) -> dict[str, dict]:
    """Per credential key: whether an override is set, plus env-var fallback visibility.

    Never returns the decrypted secret.
    """
    stored = await WorkspaceConfigRepo(session).get_section(OAUTH_CONFIG_SECTION) or {}
    status: dict[str, dict] = {}
    for key in sorted(credential_keys()):
        entry = stored.get(key, {})
        client_id = entry.get("client_id")
        client_id_set = isinstance(client_id, str) and bool(client_id.strip())
        secret_set = bool(entry.get("client_secret"))

        cls = _representative_connector_class(key)
        env_client_id_set = bool(cls and os.getenv(cls.CLIENT_ID_ENV_VAR))
        env_client_secret_set = bool(cls and os.getenv(cls.CLIENT_SECRET_ENV_VAR))

        if client_id_set and secret_set:
            secret_source = "override"
        elif env_client_id_set and env_client_secret_set:
            secret_source = "env"
        else:
            secret_source = "none"

        status[key] = {
            "client_id_set": client_id_set,
            "client_id": client_id if client_id_set else None,
            "secret_source": secret_source,
            "env_client_id_set": env_client_id_set,
        }
    return status


async def set_oauth_config(
    session: AsyncSession,
    credential_key: str,
    client_id: str | None,
    client_secret: str | None,
    actor_user_id: str | None,
) -> None:
    """Partial update: only overwrite fields that were provided (non-empty)."""
    if credential_key not in credential_keys():
        raise ValueError(f"Unknown OAuth credential key: {credential_key}")

    repo = WorkspaceConfigRepo(session)
    stored = await repo.get_section(OAUTH_CONFIG_SECTION) or {}
    entry = dict(stored.get(credential_key, {}))

    resolved_client_id = entry.get("client_id")
    if isinstance(client_id, str) and client_id.strip():
        resolved_client_id = client_id.strip()
        entry["client_id"] = resolved_client_id

    resolved_client_secret_plain = None
    if isinstance(client_secret, str) and client_secret.strip():
        resolved_client_secret_plain = client_secret.strip()
        entry["client_secret"] = encrypt_secret(resolved_client_secret_plain)
    elif entry.get("client_secret"):
        try:
            resolved_client_secret_plain = decrypt_secret(entry["client_secret"])
        except Exception:
            logger.error(
                "Failed to decrypt existing OAuth client secret during update",
                credential_key=credential_key,
            )

    stored[credential_key] = entry
    await repo.upsert(OAUTH_CONFIG_SECTION, stored, actor_user_id=actor_user_id)

    _set_cache_entry(credential_key, resolved_client_id, resolved_client_secret_plain)


async def clear_oauth_config(
    session: AsyncSession, credential_key: str, actor_user_id: str | None
) -> None:
    if credential_key not in credential_keys():
        raise ValueError(f"Unknown OAuth credential key: {credential_key}")

    repo = WorkspaceConfigRepo(session)
    stored = await repo.get_section(OAUTH_CONFIG_SECTION) or {}
    if credential_key in stored:
        del stored[credential_key]
        await repo.upsert(OAUTH_CONFIG_SECTION, stored, actor_user_id=actor_user_id)

    _clear_cache_entry(credential_key)
