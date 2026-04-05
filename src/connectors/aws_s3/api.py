"""FastAPI route handlers for AWS S3-specific endpoints."""

import os

from fastapi import Depends
from fastapi.responses import JSONResponse

from config.settings import get_index_name
from dependencies import get_connector_service, get_session_manager, get_current_user
from session_manager import User
from utils.logging_config import get_logger

from .auth import describe_s3_error, validate_s3_access
from .models import S3ConfigureBody
from .support import build_s3_config

logger = get_logger(__name__)


async def s3_defaults(
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
):
    """Return current S3 env-var defaults for pre-filling the config dialog.

    Sensitive values (secret key) are masked — only whether they are set is returned.
    """
    access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    session_token = os.getenv("AWS_SESSION_TOKEN", "")
    endpoint_url = os.getenv("AWS_S3_ENDPOINT", "")
    region = os.getenv("AWS_REGION", "")

    connections = await connector_service.connection_manager.list_connections(
        user_id=user.user_id, connector_type="aws_s3"
    )
    conn_config = connections[0].config or {} if connections else {}

    def _pick(conn_key, env_val):
        return conn_config.get(conn_key) or env_val

    return JSONResponse({
        "access_key_set": bool(access_key or conn_config.get("access_key")),
        "secret_key_set": bool(secret_key or conn_config.get("secret_key")),
        "session_token_set": bool(session_token or conn_config.get("session_token")),
        "endpoint": _pick("endpoint_url", endpoint_url),
        "region": _pick("region", region),
        "bucket_names": conn_config.get("bucket_names", []),
        "connection_id": connections[0].connection_id if connections else None,
    })


async def s3_configure(
    body: S3ConfigureBody,
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
):
    """Create or update an S3 connection with explicit credentials.

    Tests the credentials by listing buckets, then persists the connection.
    """
    existing_connections = await connector_service.connection_manager.list_connections(
        user_id=user.user_id, connector_type="aws_s3"
    )
    existing_config = existing_connections[0].config if existing_connections else {}

    conn_config, error = build_s3_config(body, existing_config)
    if error:
        return JSONResponse({"error": error}, status_code=400)

    # Test credentials
    try:
        validate_s3_access(conn_config)
    except Exception as exc:
        logger.exception("Failed to connect to S3 during credential test.")
        return JSONResponse(
            {"error": describe_s3_error(exc, conn_config.get("bucket_names"))},
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
        connector_type="aws_s3",
        name="Amazon S3",
        config=conn_config,
        user_id=user.user_id,
    )
    return JSONResponse({"connection_id": connection_id, "status": "connected"})


async def s3_list_buckets(
    connection_id: str,
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
):
    """List all buckets accessible with the stored S3 credentials."""
    connection = await connector_service.connection_manager.get_connection(connection_id)
    if not connection or connection.user_id != user.user_id:
        return JSONResponse({"error": "Connection not found"}, status_code=404)
    if connection.connector_type != "aws_s3":
        return JSONResponse({"error": "Not an S3 connection"}, status_code=400)

    try:
        buckets = validate_s3_access(connection.config)
        return JSONResponse({"buckets": buckets})
    except Exception as exc:
        logger.exception("Failed to list S3 buckets for connection %s", connection_id)
        return JSONResponse(
            {"error": describe_s3_error(exc, connection.config.get("bucket_names"))},
            status_code=500,
        )


async def s3_bucket_status(
    connection_id: str,
    connector_service=Depends(get_connector_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Return all buckets for an S3 connection with their ingestion status."""
    connection = await connector_service.connection_manager.get_connection(connection_id)
    if not connection or connection.user_id != user.user_id:
        return JSONResponse({"error": "Connection not found"}, status_code=404)
    if connection.connector_type != "aws_s3":
        return JSONResponse({"error": "Not an S3 connection"}, status_code=400)

    # 1. List all buckets from S3
    try:
        all_buckets = validate_s3_access(connection.config)
    except Exception as exc:
        logger.exception("Failed to list buckets from S3 for connection %s", connection_id)
        return JSONResponse(
            {"error": describe_s3_error(exc, connection.config.get("bucket_names"))},
            status_code=500,
        )

    # 2. Count indexed documents per bucket from OpenSearch
    ingested_counts: dict = {}
    try:
        opensearch_client = session_manager.get_user_opensearch_client(
            user.user_id, user.jwt_token
        )
        query_body = {
            "size": 0,
            "query": {"term": {"connector_type": "aws_s3"}},
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
