"""Azure Blob Storage authentication and client factory.

Supports two credential modes, both of which work against real Azure Storage
accounts and the local Azurite emulator:

- ``connection_string``: a full Azure Storage connection string
  (e.g. from the Azure Portal, or ``UseDevelopmentStorage=true`` for Azurite).
- ``account_key``: an account name + shared key, with an optional custom
  ``endpoint_url`` (used to point at Azurite or a sovereign cloud).

Resolution order for each credential: connector config dict → environment
variable. The sync ``azure-storage-blob`` SDK is used; callers offload blocking
operations onto a worker thread via ``asyncio.to_thread``.
"""

import os
from typing import Any

from utils.logging_config import get_logger

logger = get_logger(__name__)

# Public Azure Blob endpoint template (account_key mode, no custom endpoint).
_DEFAULT_BLOB_ENDPOINT = "https://{account}.blob.core.windows.net"


def _resolve_credentials(config: dict[str, Any]) -> dict[str, Any]:
    """Resolve Azure Blob credentials from config dict → environment fallback.

    Returns a dict with the resolved values needed to build a BlobServiceClient.
    Does not raise — validation happens in the builder so callers get a single,
    mode-aware error message.
    """
    auth_mode = config.get("auth_mode", "connection_string")

    connection_string = config.get("connection_string") or os.getenv(
        "AZURE_STORAGE_CONNECTION_STRING"
    )
    account_name = config.get("account_name") or os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    account_key = config.get("account_key") or os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
    # Optional custom blob endpoint (Azurite / sovereign clouds). For Azurite the
    # account-style endpoint is e.g. http://127.0.0.1:10000/devstoreaccount1.
    endpoint_url = config.get("endpoint_url") or os.getenv("AZURE_STORAGE_ENDPOINT") or None

    return {
        "auth_mode": auth_mode,
        "connection_string": connection_string,
        "account_name": account_name,
        "account_key": account_key,
        "endpoint_url": endpoint_url,
    }


def _account_name_from_connection_string(connection_string: str) -> str | None:
    """Best-effort parse of the storage account name from a connection string.

    Handles the Azurite shorthand (``UseDevelopmentStorage=true`` →
    ``devstoreaccount1``), standard ``AccountName=...`` strings, and SAS-style
    strings that only carry a ``BlobEndpoint``. Returns None if it can't be
    determined. Never raises — callers fall back to a stable label.
    """
    pairs = (p.split("=", 1) for p in connection_string.split(";") if "=" in p)
    parts = {k.strip().lower(): v.strip() for k, v in pairs}

    if parts.get("usedevelopmentstorage", "").lower() == "true":
        return "devstoreaccount1"
    if parts.get("accountname"):
        return parts["accountname"]

    # SAS-style strings expose the account only via the blob endpoint host/path,
    # e.g. https://myacct.blob.core.windows.net or http://host:10000/devstoreaccount1.
    endpoint = parts.get("blobendpoint")
    if endpoint:
        from urllib.parse import urlparse

        parsed = urlparse(endpoint)
        path = parsed.path.strip("/")
        if path:  # Azurite path-style: account is the first path segment
            return path.split("/")[0]
        host = parsed.hostname or ""
        if host:  # production host-style: account is the first label
            return host.split(".")[0]
    return None


def account_name_from_config(config: dict[str, Any]) -> str | None:
    """Resolve the storage account name from config (both auth modes).

    Used by the connector's ``get_client_id`` so status checks have a stable,
    non-raising identifier even in connection-string mode (where ``account_name``
    is implicit in the string rather than stored separately).
    """
    creds = _resolve_credentials(config)
    if creds["account_name"]:
        return creds["account_name"]
    if creds["connection_string"]:
        return _account_name_from_connection_string(creds["connection_string"])
    return None


def create_blob_service_client(config: dict[str, Any]):
    """Return a sync ``BlobServiceClient`` for the configured auth mode.

    Args:
        config: Connector config dict (see module docstring for keys).

    Raises:
        ImportError: If the ``azure-storage-blob`` package is not installed.
        ValueError: If required credentials for the selected mode are missing.
    """
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError as exc:
        raise ImportError(
            "azure-storage-blob is required for the Azure Blob connector. "
            "Install it with: pip install azure-storage-blob"
        ) from exc

    creds = _resolve_credentials(config)
    auth_mode = creds["auth_mode"]

    if auth_mode == "connection_string":
        if not creds["connection_string"]:
            raise ValueError(
                "Connection string mode requires a connection string. Provide "
                "'connection_string' in the connector config or set "
                "AZURE_STORAGE_CONNECTION_STRING."
            )
        logger.debug("Creating Azure Blob client from connection string")
        return BlobServiceClient.from_connection_string(creds["connection_string"])

    # account_key mode
    if not (creds["account_name"] and creds["account_key"]):
        raise ValueError(
            "Account key mode requires account_name and account_key. Provide them "
            "in the connector config or set AZURE_STORAGE_ACCOUNT_NAME / "
            "AZURE_STORAGE_ACCOUNT_KEY."
        )

    account_url = creds["endpoint_url"] or _DEFAULT_BLOB_ENDPOINT.format(
        account=creds["account_name"]
    )
    logger.debug("Creating Azure Blob client with account key for %s", account_url)
    return BlobServiceClient(account_url=account_url, credential=creds["account_key"])
