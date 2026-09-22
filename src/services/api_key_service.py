"""
API Key Service for managing user API keys for public API authentication.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import API_KEYS_INDEX_NAME
from db.models import ApiKey
from db.repositories import ApiKeyRepo, UserRepo
from utils.logging_config import get_logger

logger = get_logger(__name__)
API_KEY_HASH_PREFIX = "hmac-sha256:"


class APIKeyService:
    """Service for managing user API keys for public API authentication."""

    def __init__(self, session_manager=None, session_factory=None):
        self.session_manager = session_manager
        self._session_factory = session_factory

    def _generate_api_key(self) -> tuple[str, str, str]:
        """
        Generate a new API key.

        Returns:
            Tuple of (full_key, key_hash, key_prefix)
            - full_key: The complete API key to return to user (only shown once)
            - key_hash: keyed HMAC digest of the key for storage
            - key_prefix: First 12 chars for display (e.g., "orag_abc12345")
        """
        # Generate 32 bytes of random data, encode as base64url (no padding)
        random_bytes = secrets.token_urlsafe(32)

        # Create the full key with prefix
        full_key = f"orag_{random_bytes}"

        key_hash = self._hash_key(full_key)

        # Create prefix for display (orag_ + first 8 chars of random part)
        key_prefix = f"orag_{random_bytes[:8]}"

        return full_key, key_hash, key_prefix

    def _db_session(self) -> AsyncSession:
        """Open a DB session, failing if the factory wasn't wired"""
        if self._session_factory is None:
            raise RuntimeError("APIKeyService requires a DB session factory")
        return self._session_factory()

    def _get_opensearch_client(self, jwt_token: str = None):
        """Get the appropriate OpenSearch client.

        Upstream-authenticated requests can use the user credential for scoped
        reads. Writes go through the backend client so the OpenSearch user role
        can stay read-only.
        """
        from config.settings import IBM_AUTH_ENABLED, clients

        if IBM_AUTH_ENABLED and jwt_token and self.session_manager:
            return clients.create_user_opensearch_client(jwt_token)
        return clients.opensearch

    def _get_write_opensearch_client(self):
        """Return the trusted backend OpenSearch client for API-key writes."""
        from config.settings import clients

        if clients.opensearch is None:
            raise RuntimeError("Backend OpenSearch write client is unavailable")
        return clients.opensearch

    def _hash_key(self, api_key: str) -> str:
        """Create the keyed lookup digest stored in OpenSearch."""
        from config.settings import SESSION_SECRET

        digest = hmac.digest(
            SESSION_SECRET.encode("utf-8"),
            api_key.encode("utf-8"),
            "sha256",
        ).hex()
        return f"{API_KEY_HASH_PREFIX}{digest}"

    def _legacy_hash_key(self, api_key: str) -> str:
        """Return the pre-HMAC lookup digest for backwards compatibility."""
        digest = hashlib.new("sha256", usedforsecurity=False)  # nosec B324
        digest.update(api_key.encode("utf-8"))
        return digest.hexdigest()

    def _candidate_hashes(self, api_key: str) -> list[str]:
        keyed_hash = self._hash_key(api_key)
        legacy_hash = self._legacy_hash_key(api_key)
        return [keyed_hash, legacy_hash]

    async def _validate_key_opensearch(self, api_key: str) -> dict[str, Any] | None:
        """Read-only OpenSearch fallback for keys not yet copied into SQL DB."""
        try:
            key_hash = self._hash_key(api_key)
            opensearch_client = self._get_opensearch_client()
            if opensearch_client is None:
                return None

            # Search for the key by hash
            search_body = {
                "query": {
                    "bool": {
                        "must": [
                            {"terms": {"key_hash": self._candidate_hashes(api_key)}},
                            {"term": {"revoked": False}},
                        ]
                    }
                },
                "size": 1,
            }

            result = await opensearch_client.search(
                index=API_KEYS_INDEX_NAME,
                body=search_body,
            )
            hits = result.get("hits", {}).get("hits", [])
            if not hits:
                return None

            key_doc = hits[0]["_source"]

            matched_hash = key_doc.get("key_hash")

            # Update last_used_at and opportunistically migrate legacy hashes.
            try:
                write_client = self._get_write_opensearch_client()
                update_doc = {"last_used_at": datetime.now(UTC).isoformat()}
                if matched_hash != key_hash:
                    update_doc["key_hash"] = key_hash
                await write_client.update(
                    index=API_KEYS_INDEX_NAME,
                    id=key_doc["key_id"],
                    body={"doc": update_doc},
                )
            except Exception:
                pass  # Don't fail validation if update fails

            return {
                "key_id": key_doc["key_id"],
                "user_id": key_doc["user_id"],
                "user_email": key_doc["user_email"],
                "name": key_doc["name"],
            }

        except Exception as e:
            logger.error("Failed to validate API key", error=str(e))
            return None

    async def create_key(self, user_id: str, name: str) -> dict[str, Any]:
        """
        Create a new API key for a user.

        Args:
            user_id: The user's ID
            name: A friendly name for the key

        Returns:
            Dict with success status, key info, and the full key (only shown once)
        """
        try:
            # Generate the key
            full_key, key_hash, key_prefix = self._generate_api_key()

            # Create a unique key_id
            key_id = secrets.token_urlsafe(16)

            now = datetime.now(UTC)

            # Create the row to store
            row = ApiKey(
                id=key_id,
                user_id=user_id,
                name=name,
                key_hash=key_hash,
                key_prefix=key_prefix,
                created_at=now,
            )

            async with self._db_session() as session:
                await ApiKeyRepo(session).add(row)
                await session.commit()

            logger.info(
                "Created API key",
                user_id=user_id,
                key_id=key_id,
                key_prefix=key_prefix,
            )
            return {
                "success": True,
                "key_id": key_id,
                "key_prefix": key_prefix,
                "name": name,
                "created_at": now.isoformat(),
                "api_key": full_key,  # Only returned once!
            }
        except Exception as e:
            logger.error("Failed to create API key", error=str(e), user_id=user_id)
            return {"success": False, "error": str(e)}

    async def validate_key(self, api_key: str) -> dict[str, Any] | None:
        """
        Validate an API key and return user info if valid.

        Args:
            api_key: The full API key to validate

        Returns:
            Dict with user info if valid, None if invalid
        """
        try:
            # Check key format
            if not api_key or not api_key.startswith("orag_"):
                return None

            key_hash = self._hash_key(api_key)

            async with self._db_session() as session:
                repo = ApiKeyRepo(session)

                # Keyed-HMAC digest first, then the pre-HMAC legacy digest
                # so old keys migrated with a legacy hash still validate.
                # Look up in *any* state: a SQL row is authoritative, so a
                # revoked/tombstoned key must be found and rejected here rather
                # than slipping through to OpenSearch fallback (whose copy
                # is never updated on revoke/delete) and re-authenticating.
                row = await repo.get_by_hash_any_state(key_hash)
                if row is None:
                    row = await repo.get_by_hash_any_state(self._legacy_hash_key(api_key))

                if row is not None:
                    # sql row exists. If its revoked (tombstone applies to both revoke and delete)
                    # the key is invalid and we shouldnt fall back to OpenSearch
                    if row.revoked:
                        return None

                    user = await UserRepo(session).get_by_id(row.user_id)

                    result = {
                        "key_id": row.id,
                        "user_id": row.user_id,
                        "user_email": user.email if user else None,
                        "name": row.name,
                    }

                    try:
                        await repo.mark_used(row.id)
                        await session.commit()
                    except Exception:
                        await session.rollback()
                    return result

            # Not in SQL db yet, read-only fallback to OpenSearch
            return await self._validate_key_opensearch(api_key)

        except Exception as e:
            logger.error("Failed to validate API key", error=str(e))
            return None

    async def list_keys(
        self, user_id: str, oauth_subject: str, jwt_token: str | None = None
    ) -> dict[str, Any]:
        """
        List all active (non-revoked) API keys for a user (without the actual keys).

        Args:
            user_id: The user's ID
            oauth_subject: The user's OAuth subject, used only for the OpenSearch
                read fallback (OpenSearch documents key on the subject, not users.id)
            jwt_token: JWT token for OpenSearch authentication (used only for OpenSearch read fallback)

        Returns:
            Dict with list of key metadata
        """
        try:
            async with self._db_session() as session:
                rows = await ApiKeyRepo(session).list_for_user(user_id)

            if rows:
                active = [r for r in rows if not r.revoked]
                active.sort(key=lambda r: r.created_at, reverse=True)
                keys = [
                    {
                        "key_id": r.id,
                        "key_prefix": r.key_prefix,
                        "name": r.name,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                        "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
                        "revoked": r.revoked,
                    }
                    for r in active
                ]
                return {"success": True, "keys": keys}

            # No SQL db keys for this user, read-only fallback to OpenSearch
            opensearch_client = self._get_opensearch_client(jwt_token)

            # Search for user's keys
            search_body = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"user_id": oauth_subject}},
                            {"term": {"revoked": False}},
                        ]
                    }
                },
                "sort": [{"created_at": {"order": "desc"}}],
                "_source": [
                    "key_id",
                    "key_prefix",
                    "name",
                    "created_at",
                    "last_used_at",
                    "revoked",
                ],
                "size": 100,
            }

            result = await opensearch_client.search(
                index=API_KEYS_INDEX_NAME,
                body=search_body,
            )

            keys = []
            for hit in result.get("hits", {}).get("hits", []):
                keys.append(hit["_source"])

            return {"success": True, "keys": keys}

        except Exception as e:
            logger.error("Failed to list API keys", error=str(e), user_id=user_id)
            return {"success": False, "error": str(e), "keys": []}

    async def revoke_key(
        self,
        user_id: str,
        key_id: str,
    ) -> dict[str, Any]:
        """
        Revoke an API key.

        Args:
            user_id: The user's ID (for authorization)
            key_id: The key ID to revoke

        Returns:
            Dict with success status
        """
        try:
            async with self._db_session() as session:
                repo = ApiKeyRepo(session)

                # First, verify the key belongs to this user
                row = await repo.get_by_id(key_id)
                if row is None:
                    return {"success": False, "error": "Key not found"}
                if row.user_id != user_id:
                    return {"success": False, "error": "Not authorized to revoke this key"}

                await repo.revoke(key_id)
                await session.commit()

            logger.info(
                "Revoked API key",
                user_id=user_id,
                key_id=key_id,
            )
            return {"success": True}

        except Exception as e:
            logger.error(
                "Failed to revoke API key",
                error=str(e),
                user_id=user_id,
                key_id=key_id,
            )
            return {"success": False, "error": str(e)}

    async def delete_key(
        self,
        user_id: str,
        key_id: str,
    ) -> dict[str, Any]:
        """
        Delete an API key (tombstone).

        Args:
            user_id: The user's ID (for authorization)
            key_id: The key ID to delete

        Returns:
            Dict with success status
        """
        try:
            async with self._db_session() as session:
                repo = ApiKeyRepo(session)

                # First, verify the key belongs to this user
                row = await repo.get_by_id(key_id)
                if row is None:
                    return {"success": False, "error": "Key not found"}
                if row.user_id != user_id:
                    return {"success": False, "error": "Not authorized to delete this key"}

                # since a migrated key still has a live OpenSearch doc and we never write to
                # OpenSearch on delete we should Tombstone instead of hard-deleting.
                # Dropping the sql row would let validate_key's OpenSearch fallback re-auth the key.
                # TODO: once we complete migration to sql (remove opensearch read fallback),
                # we should update this to use a proper sql delete instead of soft delete
                await repo.revoke(key_id)
                await session.commit()

            logger.info(
                "Deleted API key",
                user_id=user_id,
                key_id=key_id,
            )
            return {"success": True}

        except Exception as e:
            logger.error(
                "Failed to delete API key",
                error=str(e),
                user_id=user_id,
                key_id=key_id,
            )
            return {"success": False, "error": str(e)}
