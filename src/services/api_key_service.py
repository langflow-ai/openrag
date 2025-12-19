"""
API Key Service for managing user API keys for public API authentication.
"""
import hashlib
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.settings import API_KEYS_INDEX_NAME
from utils.logging_config import get_logger

logger = get_logger(__name__)


class APIKeyService:
    """Service for managing user API keys for public API authentication."""

    def __init__(self, session_manager=None):
        self.session_manager = session_manager

    def _generate_api_key(self) -> tuple[str, str, str]:
        """
        Generate a new API key.

        Returns:
            Tuple of (full_key, key_hash, key_prefix)
            - full_key: The complete API key to return to user (only shown once)
            - key_hash: SHA-256 hash of the key for storage
            - key_prefix: First 12 chars for display (e.g., "orag_abc12345")
        """
        # Generate 32 bytes of random data, encode as base64url (no padding)
        random_bytes = secrets.token_urlsafe(32)

        # Create the full key with prefix
        full_key = f"orag_{random_bytes}"

        # Hash the full key for storage
        key_hash = hashlib.sha256(full_key.encode()).hexdigest()

        # Create prefix for display (orag_ + first 8 chars of random part)
        key_prefix = f"orag_{random_bytes[:8]}"

        return full_key, key_hash, key_prefix

    def _hash_key(self, api_key: str) -> str:
        """Hash an API key for lookup."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    async def create_key(
        self,
        user_id: str,
        user_email: str,
        name: str,
        jwt_token: str = None,
    ) -> Dict[str, Any]:
        """
        Create a new API key for a user.

        Args:
            user_id: The user's ID
            user_email: The user's email
            name: A friendly name for the key
            jwt_token: JWT token for OpenSearch authentication

        Returns:
            Dict with success status, key info, and the full key (only shown once)
        """
        try:
            # Generate the key
            full_key, key_hash, key_prefix = self._generate_api_key()

            # Create a unique key_id
            key_id = secrets.token_urlsafe(16)

            now = datetime.utcnow().isoformat()

            # Create the document to store
            key_doc = {
                "key_id": key_id,
                "key_hash": key_hash,
                "key_prefix": key_prefix,
                "user_id": user_id,
                "user_email": user_email,
                "name": name,
                "created_at": now,
                "last_used_at": None,
                "revoked": False,
            }

            # Get OpenSearch client
            from config.settings import clients
            opensearch_client = clients.opensearch

            # Index the key document
            result = await opensearch_client.index(
                index=API_KEYS_INDEX_NAME,
                id=key_id,
                body=key_doc,
                refresh="wait_for",
            )

            if result.get("result") in ("created", "updated"):
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
                    "created_at": now,
                    "api_key": full_key,  # Only returned once!
                }
            else:
                return {"success": False, "error": "Failed to create API key"}

        except Exception as e:
            logger.error("Failed to create API key", error=str(e), user_id=user_id)
            return {"success": False, "error": str(e)}

    async def validate_key(self, api_key: str) -> Optional[Dict[str, Any]]:
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

            # Hash the incoming key
            key_hash = self._hash_key(api_key)

            # Get OpenSearch client
            from config.settings import clients
            opensearch_client = clients.opensearch

            # Search for the key by hash
            search_body = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"key_hash": key_hash}},
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

            # Update last_used_at (fire and forget)
            try:
                await opensearch_client.update(
                    index=API_KEYS_INDEX_NAME,
                    id=key_doc["key_id"],
                    body={
                        "doc": {
                            "last_used_at": datetime.utcnow().isoformat()
                        }
                    },
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

    async def list_keys(
        self,
        user_id: str,
        jwt_token: str = None,
    ) -> Dict[str, Any]:
        """
        List all API keys for a user (without the actual keys).

        Args:
            user_id: The user's ID
            jwt_token: JWT token for OpenSearch authentication

        Returns:
            Dict with list of key metadata
        """
        try:
            # Get OpenSearch client
            from config.settings import clients
            opensearch_client = clients.opensearch

            # Search for user's keys
            search_body = {
                "query": {
                    "term": {"user_id": user_id}
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
        jwt_token: str = None,
    ) -> Dict[str, Any]:
        """
        Revoke an API key.

        Args:
            user_id: The user's ID (for authorization)
            key_id: The key ID to revoke
            jwt_token: JWT token for OpenSearch authentication

        Returns:
            Dict with success status
        """
        try:
            # Get OpenSearch client
            from config.settings import clients
            opensearch_client = clients.opensearch

            # First, verify the key belongs to this user
            try:
                doc = await opensearch_client.get(
                    index=API_KEYS_INDEX_NAME,
                    id=key_id,
                )

                if doc["_source"]["user_id"] != user_id:
                    return {"success": False, "error": "Not authorized to revoke this key"}

            except Exception:
                return {"success": False, "error": "Key not found"}

            # Update the key to mark as revoked
            result = await opensearch_client.update(
                index=API_KEYS_INDEX_NAME,
                id=key_id,
                body={
                    "doc": {
                        "revoked": True
                    }
                },
                refresh="wait_for",
            )

            if result.get("result") == "updated":
                logger.info(
                    "Revoked API key",
                    user_id=user_id,
                    key_id=key_id,
                )
                return {"success": True}
            else:
                return {"success": False, "error": "Failed to revoke key"}

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
        jwt_token: str = None,
    ) -> Dict[str, Any]:
        """
        Permanently delete an API key.

        Args:
            user_id: The user's ID (for authorization)
            key_id: The key ID to delete
            jwt_token: JWT token for OpenSearch authentication

        Returns:
            Dict with success status
        """
        try:
            # Get OpenSearch client
            from config.settings import clients
            opensearch_client = clients.opensearch

            # First, verify the key belongs to this user
            try:
                doc = await opensearch_client.get(
                    index=API_KEYS_INDEX_NAME,
                    id=key_id,
                )

                if doc["_source"]["user_id"] != user_id:
                    return {"success": False, "error": "Not authorized to delete this key"}

            except Exception:
                return {"success": False, "error": "Key not found"}

            # Delete the key
            result = await opensearch_client.delete(
                index=API_KEYS_INDEX_NAME,
                id=key_id,
                refresh="wait_for",
            )

            if result.get("result") == "deleted":
                logger.info(
                    "Deleted API key",
                    user_id=user_id,
                    key_id=key_id,
                )
                return {"success": True}
            else:
                return {"success": False, "error": "Failed to delete key"}

        except Exception as e:
            logger.error(
                "Failed to delete API key",
                error=str(e),
                user_id=user_id,
                key_id=key_id,
            )
            return {"success": False, "error": str(e)}
