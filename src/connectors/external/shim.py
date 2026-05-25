"""Mode-selecting shim for any connector registered in ``openrag_connectors``.

``ConnectionManager`` constructs this class for every external connector
type. ``ExternalConnector`` is a real ``BaseConnector`` subclass so type
hints and ``isinstance`` checks still work; the connector's identity
(``CONNECTOR_NAME`` / ``CLIENT_ID_ENV_VAR`` / ...) is proxied from the
upstream class so existing OpenRAG machinery (auth helpers, metadata
endpoints) treats it the same as a built-in.

Mode (all external connectors, all-or-nothing):

    OPENRAG_EXTERNAL_CONNECTORS_MODE=library  (default)  → in-process via openrag_connectors
    OPENRAG_EXTERNAL_CONNECTORS_MODE=service              → HTTP client to the connectors service

Service mode also requires ``OPENRAG_CONNECTORS_URL`` and
``OPENRAG_CONNECTORS_TOKEN``.
"""

import logging
import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from ..base import BaseConnector, ConnectorDocument

if TYPE_CHECKING:
    from .library_backend import LibraryBackend
    from .service_backend import ServiceBackend

logger = logging.getLogger(__name__)


class ExternalConnector(BaseConnector):
    """Mode-selecting adapter. ``connector_type`` is passed in by ConnectionManager."""

    _backend: "LibraryBackend | ServiceBackend"

    def __init__(self, connector_type: str, config: dict[str, Any]):
        if config is None:
            config = {}
        super().__init__(config)
        self.connector_type = connector_type

        # Proxy class-level metadata from the upstream connector so that
        # OpenRAG code that reads `instance.CONNECTOR_NAME` /
        # `CLIENT_ID_ENV_VAR` / etc. transparently sees the connector's
        # real identity.
        from openrag_connectors import get as get_connector_cls

        upstream_cls = get_connector_cls(connector_type)
        self.CLIENT_ID_ENV_VAR = upstream_cls.CLIENT_ID_ENV_VAR
        self.CLIENT_SECRET_ENV_VAR = upstream_cls.CLIENT_SECRET_ENV_VAR
        self.CONNECTOR_NAME = upstream_cls.CONNECTOR_NAME
        self.CONNECTOR_DESCRIPTION = upstream_cls.CONNECTOR_DESCRIPTION
        self.CONNECTOR_ICON = upstream_cls.CONNECTOR_ICON

        mode = os.environ.get("OPENRAG_EXTERNAL_CONNECTORS_MODE", "library").lower()

        if mode == "service":
            from .service_backend import ServiceBackend

            self._backend = ServiceBackend(connector_type, config)
        else:
            from .library_backend import LibraryBackend

            self._backend = LibraryBackend(connector_type, config)

        # Expose the combined webhook fast-path only when the backend
        # implements it (service mode does; library mode falls back to the
        # 3-method flow that BaseConnector already provides).
        if hasattr(self._backend, "process_webhook_full"):
            self.process_webhook_full = self._backend.process_webhook_full

        logger.debug("External connector %r initialized in %s mode", connector_type, mode)

    # ── BaseConnector contract ─────────────────────────────────────────────

    async def authenticate(self) -> bool:
        ok = await self._backend.authenticate()
        self._authenticated = ok
        return ok

    async def list_files(
        self,
        page_token: str | None = None,
        max_files: int | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        return await self._backend.list_files(page_token=page_token, max_files=max_files)

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        return await self._backend.get_file_content(file_id)

    async def setup_subscription(self) -> str:
        return await self._backend.setup_subscription()

    async def cleanup_subscription(self, subscription_id: str) -> bool:
        return await self._backend.cleanup_subscription(subscription_id)

    async def handle_webhook(self, payload: dict[str, Any]) -> list[str]:
        return await self._backend.handle_webhook(payload)

    def handle_webhook_validation(
        self, request_method: str, headers: dict[str, str], query_params: dict[str, str]
    ) -> str | None:
        return self._backend.handle_webhook_validation(request_method, headers, query_params)

    def extract_webhook_channel_id(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> str | None:
        return self._backend.extract_webhook_channel_id(payload, headers)

    # ── OAuth helpers (duck-typed by src/api/auth.py for OAuth connectors) ──

    def get_auth_url(self) -> str:
        return self._backend.get_auth_url()

    async def handle_oauth_callback(self, auth_code: str) -> dict[str, Any]:
        return await self._backend.handle_oauth_callback(auth_code)

    @property
    def oauth(self):
        return getattr(self._backend, "oauth", None)
