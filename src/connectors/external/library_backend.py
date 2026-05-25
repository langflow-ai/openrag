"""Library-mode backend: in-process call into ``openrag_connectors.<type>``."""

from pathlib import Path
from typing import Any, Dict, List, Optional


class LibraryBackend:
    """Wraps an upstream connector class so the shim can delegate."""

    def __init__(self, connector_type: str, config: dict[str, Any]):
        from openrag_connectors import get as get_connector_cls

        from .encrypted_token_store import EncryptedFileTokenStore

        self.connector_type = connector_type

        # Token persistence: encrypted-at-rest under OpenRAG's data dir,
        # one file per connection. The connector accepts any TokenStore
        # via config["token_store"]; we always inject our encrypted one.
        if config.get("token_store") is None:
            from config.paths import get_data_file

            connection_id = config.get("connection_id", "default")
            token_file = config.get("token_file") or get_data_file(
                f"{connector_type}_token_{connection_id}.json"
            )
            Path(token_file).parent.mkdir(parents=True, exist_ok=True)
            config = {**config, "token_store": EncryptedFileTokenStore(token_file)}

        cls = get_connector_cls(connector_type)
        self._connector = cls(config)

    # ── BaseConnector contract ─────────────────────────────────────────────

    async def authenticate(self) -> bool:
        return await self._connector.authenticate()

    async def list_files(
        self,
        page_token: str | None = None,
        max_files: int | None = None,
    ) -> dict[str, Any]:
        return await self._connector.list_files(page_token=page_token, max_files=max_files)

    async def get_file_content(self, file_id: str):
        return await self._connector.get_file_content(file_id)

    async def setup_subscription(self) -> str:
        return await self._connector.setup_subscription()

    async def cleanup_subscription(self, subscription_id: str) -> bool:
        return await self._connector.cleanup_subscription(subscription_id)

    async def handle_webhook(self, payload: dict[str, Any]) -> list[str]:
        return await self._connector.handle_webhook(payload)

    def handle_webhook_validation(
        self, method: str, headers: dict[str, str], query_params: dict[str, str]
    ) -> str | None:
        return self._connector.handle_webhook_validation(method, headers, query_params)

    def extract_webhook_channel_id(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> str | None:
        return self._connector.extract_webhook_channel_id(payload, headers)

    # ── OAuth helpers (called by src/api/auth.py via duck typing) ──────────

    def get_auth_url(self) -> str:
        return self._connector.get_auth_url()

    async def handle_oauth_callback(self, auth_code: str) -> dict[str, Any]:
        return await self._connector.handle_oauth_callback(auth_code)

    @property
    def oauth(self):
        return getattr(self._connector, "oauth", None)
