"""FastAPI route handlers for Azure Blob-specific endpoints."""

import asyncio
import os

from fastapi import Depends
from fastapi.responses import JSONResponse

from config.settings import get_index_name
from dependencies import get_connector_service, get_current_user, get_session_manager
from session_manager import User
from utils.logging_config import get_logger

from .auth import create_blob_service_client
from .models import AzureBlobConfigureBody
from .support import build_azure_blob_config

logger = get_logger(__name__)


def _list_container_names(config: dict) -> list[str]:
    """List container names for a resolved Azure Blob config (sync helper)."""
    client = create_blob_service_client(config)
    return [c.name for c in client.list_containers()]


async def azure_blob_defaults(
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
):
    """Return current Azure Blob env-var defaults for pre-filling the config dialog.

    Sensitive values (connection string, account key) are masked — only whether
    they are set is returned, not the actual values.
    """
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
    account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", "")
    account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY", "")
    endpoint = os.getenv("AZURE_STORAGE_ENDPOINT", "")

    connections = await connector_service.connection_manager.list_connections(
        user_id=user.user_id, connector_type="azure_blob"
    )
    conn_config = connections[0].config or {} if connections else {}

    def _pick(conn_key, env_val):
        """Prefer connection config value over env var."""
        return conn_config.get(conn_key) or env_val

    has_conn_str = bool(connection_string or conn_config.get("connection_string"))
    has_account_key = bool(account_key or conn_config.get("account_key"))

    return JSONResponse(
        {
            "connection_string_set": has_conn_str,
            "account_name": _pick("account_name", account_name),
            "account_key_set": has_account_key,
            "endpoint": _pick("endpoint_url", endpoint),
            "auth_mode": conn_config.get(
                "auth_mode",
                "account_key" if (has_account_key and not has_conn_str) else "connection_string",
            ),
            "container_names": conn_config.get("container_names", []),
            "connection_id": connections[0].connection_id if connections else None,
        }
    )


async def azure_blob_test(
    body: AzureBlobConfigureBody,
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
):
    """Validate Azure Blob credentials and list containers WITHOUT persisting.

    Backs the settings dialog's "Test Connection" action so testing or refreshing
    credentials never creates or mutates a saved connection (and so the stored
    container selection is never clobbered). Persistence happens only in
    ``azure_blob_configure`` on the final save. Credential resolution mirrors
    ``azure_blob_configure`` (request body → env → existing connection config).
    """
    existing_connections = await connector_service.connection_manager.list_connections(
        user_id=user.user_id, connector_type="azure_blob"
    )
    existing_config = existing_connections[0].config if existing_connections else {}

    conn_config, error = build_azure_blob_config(body, existing_config)
    if error:
        return JSONResponse({"error": error}, status_code=400)

    # The azure-storage-blob SDK is sync; offload to keep the event loop free.
    try:
        containers = await asyncio.to_thread(_list_container_names, conn_config)
    except Exception:
        logger.exception("Failed to connect to Azure Blob during credential test.")
        return JSONResponse(
            {"error": "Could not connect to Azure Blob with the provided configuration."},
            status_code=400,
        )

    return JSONResponse({"containers": containers})


async def azure_blob_configure(
    body: AzureBlobConfigureBody,
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
):
    """Create or update an Azure Blob connection with explicit credentials.

    Tests the credentials by listing containers, then persists the connection.
    Credentials are stored in the connection config dict (encrypted at rest) so
    the connector works even without system-level env vars.
    """
    existing_connections = await connector_service.connection_manager.list_connections(
        user_id=user.user_id, connector_type="azure_blob"
    )
    existing_config = existing_connections[0].config if existing_connections else {}

    conn_config, error = build_azure_blob_config(body, existing_config)
    if error:
        return JSONResponse({"error": error}, status_code=400)

    # Test credentials by listing containers. The azure-storage-blob SDK is sync,
    # so offload to a worker thread to keep the event loop responsive.
    try:
        await asyncio.to_thread(_list_container_names, conn_config)
    except Exception:
        logger.exception("Failed to connect to Azure Blob during credential test.")
        return JSONResponse(
            {"error": "Could not connect to Azure Blob with the provided configuration."},
            status_code=400,
        )

    # Persist: update existing connection or create a new one.
    if body.connection_id:
        existing = await connector_service.connection_manager.get_connection(body.connection_id)
        if existing and existing.user_id == user.user_id:
            await connector_service.connection_manager.update_connection(
                connection_id=body.connection_id,
                config=conn_config,
            )
            connector_service.connection_manager.active_connectors.pop(body.connection_id, None)
            return JSONResponse({"connection_id": body.connection_id, "status": "connected"})

    connection_id = await connector_service.connection_manager.create_connection(
        connector_type="azure_blob",
        name="Azure Blob Storage",
        config=conn_config,
        user_id=user.user_id,
    )
    return JSONResponse({"connection_id": connection_id, "status": "connected"})


async def azure_blob_list_containers(
    connection_id: str,
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
):
    """List containers for an Azure Blob connection, honoring the ingestion restriction.

    When the connection has a non-empty container_names allowlist, only those
    containers are returned; otherwise all accessible containers are listed.
    """
    connection = await connector_service.connection_manager.get_connection(connection_id)
    if not connection or connection.user_id != user.user_id:
        return JSONResponse({"error": "Connection not found"}, status_code=404)
    if connection.connector_type != "azure_blob":
        return JSONResponse({"error": "Not an Azure Blob connection"}, status_code=400)

    try:
        containers = await asyncio.to_thread(_list_container_names, connection.config)
        allowed_containers = connection.config.get("container_names") or []
        if allowed_containers:
            allowed_set = set(allowed_containers)
            containers = [c for c in containers if c in allowed_set]
        return JSONResponse({"containers": containers})
    except Exception:
        logger.exception("Failed to list Azure Blob containers for connection %s", connection_id)
        return JSONResponse({"error": "Failed to list containers"}, status_code=500)


async def azure_blob_container_status(
    connection_id: str,
    connector_service=Depends(get_connector_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Return all containers for an Azure Blob connection with ingestion status.

    Each entry includes the container name, whether it has been ingested
    (is_synced), and the count of indexed documents from that container.
    """
    connection = await connector_service.connection_manager.get_connection(connection_id)
    if not connection or connection.user_id != user.user_id:
        return JSONResponse({"error": "Connection not found"}, status_code=404)
    if connection.connector_type != "azure_blob":
        return JSONResponse({"error": "Not an Azure Blob connection"}, status_code=400)

    # 1. List containers, honoring the saved ingestion restriction. When the
    # connection has a non-empty container_names allowlist, only those
    # containers are browsable; otherwise all accessible containers are shown.
    try:
        all_containers = await asyncio.to_thread(_list_container_names, connection.config)
    except Exception:
        logger.exception("Failed to list Azure Blob containers for connection %s", connection_id)
        return JSONResponse({"error": "Failed to list containers"}, status_code=500)

    allowed_containers = connection.config.get("container_names") or []
    if allowed_containers:
        allowed_set = set(allowed_containers)
        all_containers = [c for c in all_containers if c in allowed_set]

    # 2. Count indexed documents per container from OpenSearch.
    ingested_counts: dict = {}
    try:
        opensearch_client = session_manager.get_user_opensearch_client(user.user_id, user.jwt_token)
        query_body = {
            "size": 0,
            "query": {"term": {"connector_type": "azure_blob"}},
            "aggs": {"doc_ids": {"terms": {"field": "document_id", "size": 50000}}},
        }
        index_name = get_index_name()
        os_resp = await opensearch_client.search(index=index_name, body=query_body)
        for bucket_entry in os_resp.get("aggregations", {}).get("doc_ids", {}).get("buckets", []):
            doc_id = bucket_entry["key"]
            if "::" in doc_id:
                container_name = doc_id.split("::")[0]
                ingested_counts[container_name] = ingested_counts.get(container_name, 0) + 1
    except Exception:
        logger.warning(
            "Failed to aggregate Azure Blob ingestion counts for connection %s; "
            "container status will show zero counts",
            connection_id,
            exc_info=True,
        )  # OpenSearch unavailable / query failed — show zero counts

    result = [
        {
            "name": container,
            "ingested_count": ingested_counts.get(container, 0),
            "is_synced": ingested_counts.get(container, 0) > 0,
        }
        for container in all_containers
    ]
    return JSONResponse({"containers": result})
