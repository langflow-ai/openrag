"""Azure Blob Storage connector for OpenRAG.

Enterprise/SaaS-only ``bucket``-kind connector, gated by ``IBM_AUTH_ENABLED``
(or ``OPENRAG_DEV_AZURE_BLOB=true`` for local dev/Azurite testing). Uses the
official sync ``azure-storage-blob`` SDK; all
blocking SDK calls are offloaded onto a worker thread with ``asyncio.to_thread``
so the event loop stays responsive while staying consistent with the cached
client lifecycle used by the AWS S3 / IBM COS connectors.

DLS (v1): owner-based. The connector returns an empty-principal ``DocumentACL``;
``service.process_connector_document`` assigns ``owner`` to the ingesting
OpenRAG user. Container→group principal mapping is a planned fast-follow.
"""

import asyncio
import mimetypes
import os
from datetime import UTC, datetime
from posixpath import basename
from typing import Any

from config.settings import IBM_AUTH_ENABLED, is_dev_azure_blob_enabled
from connectors.base import BaseConnector, ConnectorDocument, DocumentACL
from utils.logging_config import get_logger

from .auth import account_name_from_config, create_blob_service_client

logger = get_logger(__name__)

# Separator used in composite file IDs: "<container>::<blob>"
_ID_SEPARATOR = "::"


def _make_file_id(container: str, blob: str) -> str:
    return f"{container}{_ID_SEPARATOR}{blob}"


def _split_file_id(file_id: str) -> tuple[str, str]:
    """Split a composite file ID into (container, blob). Raises ValueError if invalid."""
    if _ID_SEPARATOR not in file_id:
        raise ValueError(f"Invalid Azure Blob file ID (missing separator): {file_id!r}")
    container, blob = file_id.split(_ID_SEPARATOR, 1)
    return container, blob


class AzureBlobConnector(BaseConnector):
    """Connector for Azure Blob Storage.

    Supports connection-string and account-name/key credential modes. Both work
    against real Azure accounts and the Azurite emulator. Credentials are read
    from the connector config dict first, then from environment variables.

    Config dict keys:
        auth_mode (str): "connection_string" (default) or "account_key".
        connection_string (str): Overrides AZURE_STORAGE_CONNECTION_STRING.
        account_name (str): Overrides AZURE_STORAGE_ACCOUNT_NAME.
        account_key (str): Overrides AZURE_STORAGE_ACCOUNT_KEY.
        endpoint_url (str): Optional custom blob endpoint (Azurite / sovereign).
        container_names (list[str]): Containers to ingest from. If empty, all
            accessible containers are used.
        prefix (str): Optional blob name prefix filter.
        connection_id (str): Connection identifier used for logging.
    """

    CONNECTOR_TYPE = "azure_blob"
    CONNECTOR_KIND = "bucket"
    CONNECTOR_NAME = "Azure Blob Storage"
    CONNECTOR_DESCRIPTION = "Add knowledge from Azure Blob Storage"
    CONNECTOR_ICON = "azure-blob"
    # connection_string / account_key are Azure-specific and must be encrypted at rest.
    SECRET_CONFIG_KEYS = ("connection_string", "account_key")

    # BaseConnector uses these for the default env-availability probe; the
    # bucket-kind override below makes availability hinge on IBM_AUTH_ENABLED
    # (or OPENRAG_DEV_AZURE_BLOB for local dev).
    CLIENT_ID_ENV_VAR = "AZURE_STORAGE_ACCOUNT_NAME"
    CLIENT_SECRET_ENV_VAR = "AZURE_STORAGE_ACCOUNT_KEY"

    @classmethod
    def is_available(cls, manager, user_id=None) -> bool:
        # Gated by feature flag like the other bucket connectors (aws_s3, ibm_cos).
        # OPENRAG_DEV_AZURE_BLOB=true bypasses the IBM_AUTH_ENABLED requirement for
        # local dev testing (e.g. against Azurite). Never use in production.
        return IBM_AUTH_ENABLED or is_dev_azure_blob_enabled()

    @classmethod
    def register_routes(cls, app) -> None:
        from .api import (
            azure_blob_configure,
            azure_blob_container_status,
            azure_blob_defaults,
            azure_blob_list_containers,
            azure_blob_test,
        )

        # Registered before generic /{connector_type}/... to avoid shadowing.
        app.add_api_route(
            "/connectors/azure_blob/defaults",
            azure_blob_defaults,
            methods=["GET"],
            tags=["internal"],
        )
        # Non-persisting credential validation + container listing (Test Connection).
        app.add_api_route(
            "/connectors/azure_blob/test",
            azure_blob_test,
            methods=["POST"],
            tags=["internal"],
        )
        app.add_api_route(
            "/connectors/azure_blob/configure",
            azure_blob_configure,
            methods=["POST"],
            tags=["internal"],
        )
        app.add_api_route(
            "/connectors/azure_blob/{connection_id}/containers",
            azure_blob_list_containers,
            methods=["GET"],
            tags=["internal"],
        )
        app.add_api_route(
            "/connectors/azure_blob/{connection_id}/container-status",
            azure_blob_container_status,
            methods=["GET"],
            tags=["internal"],
        )

    def get_client_id(self) -> str:
        """Return the storage account name; used by status checks / availability probe.

        Must not raise in connection-string mode: the account name is implicit in
        the string rather than stored separately, so the status endpoint
        (api/connectors.py) would otherwise mark an authenticated connection as
        unauthenticated and the UI would keep showing "Connect". Falls back to a
        stable label when the account can't be parsed (e.g. SAS-only strings).
        """
        val = account_name_from_config(self.config)
        if val:
            return val
        if self.config.get("auth_mode", "connection_string") == "connection_string" and (
            self.config.get("connection_string") or os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        ):
            return "azure_blob"
        raise ValueError(
            "Azure Blob credentials not set. Provide 'account_name' (account_key mode) "
            "or a 'connection_string'."
        )

    def get_client_secret(self) -> str:
        """Return account key / connection string; used by the availability probe."""
        val = (
            self.config.get("account_key")
            or self.config.get("connection_string")
            or os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
            or os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        )
        if val:
            return val
        raise ValueError(
            "Azure Blob credentials not set. Provide 'account_key' (account_key mode) "
            "or a 'connection_string'."
        )

    def __init__(self, config: dict[str, Any]):
        if config is None:
            config = {}
        super().__init__(config)

        self.container_names: list[str] = config.get("container_names") or []
        self.prefix: str = config.get("prefix", "")
        self.connection_id: str = config.get("connection_id", "default")

        self._client = None  # Lazy-initialised, cached BlobServiceClient

    @property
    def bucket_names(self) -> list[str]:
        """Alias of ``container_names`` for the generic ``bucket``-kind sync path.

        The connector API (``api/connectors.py``) drives per-bucket sync and the
        file-picker bucket filter through ``connector.bucket_names`` (the term
        S3/IBM COS use). Azure's domain name for the same concept is a
        *container*, so we expose ``bucket_names`` as a read/write alias to
        satisfy that contract without renaming the Azure-accurate attribute.
        """
        return self.container_names

    @bucket_names.setter
    def bucket_names(self, value: list[str]) -> None:
        self.container_names = value or []

    def _get_client(self):
        """Return (and cache) the BlobServiceClient for this connection."""
        if self._client is None:
            self._client = create_blob_service_client(self.config)
        return self._client

    # ------------------------------------------------------------------
    # Internal sync helpers (run via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _list_container_names_sync(self) -> list[str]:
        client = self._get_client()
        return [c.name for c in client.list_containers()]

    def _resolve_container_names_sync(self) -> list[str]:
        """Return configured container names, or auto-discover all accessible ones."""
        if self.container_names:
            return self.container_names
        try:
            containers = self._list_container_names_sync()
            logger.debug("Azure Blob auto-discovered %d container(s)", len(containers))
            return containers
        except Exception as exc:
            logger.warning("Azure Blob could not auto-discover containers: %s", exc)
            return []

    def _list_files_sync(self, max_files: int | None) -> list[dict[str, Any]]:
        client = self._get_client()
        files: list[dict[str, Any]] = []

        for container_name in self._resolve_container_names_sync():
            try:
                container_client = client.get_container_client(container_name)
                blob_iter = (
                    container_client.list_blobs(name_starts_with=self.prefix)
                    if self.prefix
                    else container_client.list_blobs()
                )
                for blob in blob_iter:
                    if blob.name.endswith("/"):
                        continue  # skip virtual directory markers
                    last_modified = getattr(blob, "last_modified", None)
                    files.append(
                        {
                            "id": _make_file_id(container_name, blob.name),
                            "name": basename(blob.name) or blob.name,
                            # "bucket" is the shared bucket-connector contract key
                            # (matches aws_s3 / ibm_cos) that browse_connection_files
                            # and the file browser read; Azure's domain term is
                            # "container", preserved in the id and metadata.
                            "bucket": container_name,
                            "key": blob.name,
                            "size": getattr(blob, "size", 0),
                            "modified_time": last_modified.isoformat() if last_modified else None,
                        }
                    )
                    if max_files and len(files) >= max_files:
                        return files
            except Exception as exc:
                logger.error("Failed to list blobs in Azure container %s: %s", container_name, exc)
                continue

        return files

    def _download_blob_sync(self, container: str, blob: str) -> dict[str, Any]:
        client = self._get_client()
        blob_client = client.get_blob_client(container=container, blob=blob)
        downloader = blob_client.download_blob()
        content: bytes = downloader.readall()
        props = getattr(downloader, "properties", None)
        content_type = ""
        last_modified = None
        size = len(content)
        if props is not None:
            settings = getattr(props, "content_settings", None)
            content_type = getattr(settings, "content_type", "") or ""
            last_modified = getattr(props, "last_modified", None)
            size = getattr(props, "size", None) or len(content)
        return {
            "content": content,
            "content_type": content_type,
            "last_modified": last_modified,
            "size": size,
        }

    # ------------------------------------------------------------------
    # BaseConnector abstract method implementations
    # ------------------------------------------------------------------

    async def authenticate(self) -> bool:
        """Validate credentials by listing containers on the storage account."""
        try:
            await asyncio.to_thread(self._list_container_names_sync)
            self._authenticated = True
            logger.debug("Azure Blob authenticated for connection %s", self.connection_id)
            return True
        except Exception as exc:
            logger.warning("Azure Blob authentication failed: %s", exc)
            self._authenticated = False
            return False

    async def list_files(
        self,
        page_token: str | None = None,
        max_files: int | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """List blobs across all configured (or auto-discovered) containers.

        The Azure SDK paginates internally, so a single pass returns all blobs;
        ``next_page_token`` is always None.
        """
        files = await asyncio.to_thread(self._list_files_sync, max_files)
        return {"files": files, "next_page_token": None}

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        """Download a blob and return a ConnectorDocument.

        Args:
            file_id: Composite ID in the form "<container>::<blob>".
        """
        container_name, blob_name = _split_file_id(file_id)
        result = await asyncio.to_thread(self._download_blob_sync, container_name, blob_name)

        content: bytes = result["content"]
        last_modified: datetime = result["last_modified"] or datetime.now(UTC)
        size: int = result["size"]

        # Prefer the blob's stored content type, but fall back to an extension
        # guess when it is missing or the generic octet-stream default.
        raw_content_type = result["content_type"]
        if raw_content_type and raw_content_type != "application/octet-stream":
            mime_type: str = raw_content_type
        else:
            mime_type = mimetypes.guess_type(blob_name)[0] or "application/octet-stream"

        filename = basename(blob_name) or blob_name

        # Owner-based DLS (v1): no per-blob principals — ownership is assigned to
        # the ingesting OpenRAG user by service.process_connector_document.
        acl = DocumentACL(owner=None, allowed_users=[], allowed_groups=[], allowed_principals=[])

        return ConnectorDocument(
            id=file_id,
            filename=filename,
            mimetype=mime_type,
            content=content,
            source_url=f"azure://{container_name}/{blob_name}",
            acl=acl,
            modified_time=last_modified,
            created_time=last_modified,  # Azure Blob does not expose a creation time
            metadata={
                "azure_container": container_name,
                "azure_blob": blob_name,
                "size": size,
            },
        )

    # ------------------------------------------------------------------
    # Webhook / subscription stubs (Azure Event Grid is out of scope here)
    # ------------------------------------------------------------------

    async def setup_subscription(self) -> str:
        """No-op: Azure Blob change notifications are out of scope for this connector."""
        return ""

    async def handle_webhook(self, payload: dict[str, Any]) -> list[str]:
        """No-op: webhooks are not supported in this connector version."""
        return []

    def extract_webhook_channel_id(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> str | None:
        return None

    async def cleanup_subscription(self, subscription_id: str) -> bool:
        """No-op: no subscription to clean up."""
        return True
