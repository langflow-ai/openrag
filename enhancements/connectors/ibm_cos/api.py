"""FastAPI route handlers for IBM COS-specific endpoints."""

import os

from fastapi import Depends
from fastapi.responses import JSONResponse

from config.settings import get_index_name
from dependencies import get_connector_service, get_session_manager, get_current_user
from session_manager import User
from utils.logging_config import get_logger

from .auth import create_ibm_cos_client, create_ibm_cos_resource
from .models import IBMCOSConfigureBody
from .support import build_ibm_cos_config

logger = get_logger(__name__)


async def ibm_cos_defaults(
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
):
    """Return current IBM COS env-var defaults for pre-filling the config dialog.

    Sensitive values (API key, HMAC secret) are masked — only whether they are
    set is returned, not the actual values.
    """
    api_key = os.getenv("IBM_COS_API_KEY", "")
    service_instance_id = os.getenv("IBM_COS_SERVICE_INSTANCE_ID", "")
    endpoint = os.getenv("IBM_COS_ENDPOINT", "")
    hmac_access_key = os.getenv("IBM_COS_HMAC_ACCESS_KEY_ID", "")
    hmac_secret_key = os.getenv("IBM_COS_HMAC_SECRET_ACCESS_KEY", "")
    disable_iam = os.getenv("OPENRAG_IBM_COS_IAM_UI", "").lower() not in ("1", "true", "yes")

    connections = await connector_service.connection_manager.list_connections(
        user_id=user.user_id, connector_type="ibm_cos"
    )
    conn_config = connections[0].config or {} if connections else {}

    def _pick(conn_key, env_val):
        """Prefer connection config value over env var."""
        return conn_config.get(conn_key) or env_val

    return JSONResponse({
        "api_key_set": bool(api_key or conn_config.get("api_key")),
        "service_instance_id": _pick("service_instance_id", service_instance_id),
        "endpoint": _pick("endpoint_url", endpoint),
        "hmac_access_key_set": bool(hmac_access_key or conn_config.get("hmac_access_key")),
        "hmac_secret_key_set": bool(hmac_secret_key or conn_config.get("hmac_secret_key")),
        "auth_mode": conn_config.get(
            "auth_mode",
            "hmac" if (disable_iam or not (api_key or conn_config.get("api_key"))) else "iam",
        ),
        "disable_iam": disable_iam,
        "bucket_names": conn_config.get("bucket_names", []),
        "connection_id": connections[0].connection_id if connections else None,
    })


async def ibm_cos_configure(
    body: IBMCOSConfigureBody,
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
):
    """Create or update an IBM COS connection with explicit credentials.

    Tests the credentials by listing buckets, then persists the connection.
    Credentials are stored in the connection config dict (not env vars) so
    the connector works even without system-level env vars.
    """
    existing_connections = await connector_service.connection_manager.list_connections(
        user_id=user.user_id, connector_type="ibm_cos"
    )
    existing_config = existing_connections[0].config if existing_connections else {}

    conn_config, error = build_ibm_cos_config(body, existing_config)
    if error:
        return JSONResponse({"error": error}, status_code=400)

    # Test credentials — IAM uses client (avoids ibm_botocore discovery-call bug),
    # HMAC uses resource (S3-compatible, works with MinIO).
    try:
        if conn_config.get("auth_mode", "iam") == "hmac":
            cos = create_ibm_cos_resource(conn_config)
            list(cos.buckets.all())
        else:
            cos = create_ibm_cos_client(conn_config)
            cos.list_buckets()
    except Exception:
        logger.exception("Failed to connect to IBM COS during credential test.")
        return JSONResponse(
            {"error": "Could not connect to IBM COS with the provided configuration."},
            status_code=400,
        )

    # Persist: update existing connection or create a new one
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
        connector_type="ibm_cos",
        name="IBM Cloud Object Storage",
        config=conn_config,
        user_id=user.user_id,
    )
    return JSONResponse({"connection_id": connection_id, "status": "connected"})


async def ibm_cos_list_buckets(
    connection_id: str,
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
):
    """List all buckets accessible with the stored IBM COS credentials."""
    connection = await connector_service.connection_manager.get_connection(connection_id)
    if not connection or connection.user_id != user.user_id:
        return JSONResponse({"error": "Connection not found"}, status_code=404)
    if connection.connector_type != "ibm_cos":
        return JSONResponse({"error": "Not an IBM COS connection"}, status_code=400)

    try:
        cfg = connection.config
        if cfg.get("auth_mode", "iam") == "hmac":
            cos = create_ibm_cos_resource(cfg)
            buckets = [b.name for b in cos.buckets.all()]
        else:
            cos = create_ibm_cos_client(cfg)
            buckets = [b["Name"] for b in cos.list_buckets().get("Buckets", [])]
        return JSONResponse({"buckets": buckets})
    except Exception:
        logger.exception("Failed to list IBM COS buckets for connection %s", connection_id)
        return JSONResponse({"error": "Failed to list buckets"}, status_code=500)


async def ibm_cos_bucket_status(
    connection_id: str,
    connector_service=Depends(get_connector_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Return all buckets for an IBM COS connection with their ingestion status.

    Each entry includes the bucket name, whether it has been ingested (is_synced),
    and the count of indexed documents from that bucket.
    """
    connection = await connector_service.connection_manager.get_connection(connection_id)
    if not connection or connection.user_id != user.user_id:
        return JSONResponse({"error": "Connection not found"}, status_code=404)
    if connection.connector_type != "ibm_cos":
        return JSONResponse({"error": "Not an IBM COS connection"}, status_code=400)

    # 1. List all buckets from COS
    try:
        cfg = connection.config
        cos = create_ibm_cos_resource(cfg)
        all_buckets = [b.name for b in cos.buckets.all()]
    except Exception:
        logger.exception("Failed to list IBM COS buckets for connection %s", connection_id)
        return JSONResponse({"error": "Failed to list buckets"}, status_code=500)

    # 2. Count indexed documents per bucket from OpenSearch
    ingested_counts: dict = {}
    try:
        opensearch_client = session_manager.get_user_opensearch_client(
            user.user_id, user.jwt_token
        )
        query_body = {
            "size": 0,
            "query": {"term": {"connector_type": "ibm_cos"}},
            "aggs": {
                "doc_ids": {
                    "terms": {"field": "document_id", "size": 50000}
                }
            },
        }
        index_name = get_index_name()
        os_resp = opensearch_client.search(index=index_name, body=query_body)
        for bucket_entry in os_resp.get("aggregations", {}).get("doc_ids", {}).get("buckets", []):
            doc_id = bucket_entry["key"]
            if "::" in doc_id:
                bucket_name = doc_id.split("::")[0]
                ingested_counts[bucket_name] = ingested_counts.get(bucket_name, 0) + 1
    except Exception:
        pass  # OpenSearch unavailable — show zero counts

    result = [
        {
            "name": bucket,
            "ingested_count": ingested_counts.get(bucket, 0),
            "is_synced": ingested_counts.get(bucket, 0) > 0,
        }
        for bucket in all_buckets
    ]
    return JSONResponse({"buckets": result})
