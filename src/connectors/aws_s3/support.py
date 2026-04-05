"""Support helpers for AWS S3 API endpoints.

Contains pure (non-async) business logic for credential resolution and
config dict construction, keeping the route handlers thin.
"""

import os
from typing import Dict, Optional, Tuple

from .models import S3ConfigureBody


def build_s3_config(
    body: S3ConfigureBody,
    existing_config: Dict,
) -> Tuple[Dict, Optional[str]]:
    """Resolve S3 credentials and build the connection config dict.

    Resolution order for each credential: request body → environment variable
    → existing connection config.

    Returns:
        (conn_config, None)  on success
        ({}, error_message)  on validation failure
    """
    access_key = (
        body.access_key
        or os.getenv("AWS_ACCESS_KEY_ID")
        or existing_config.get("access_key")
    )
    secret_key = (
        body.secret_key
        or os.getenv("AWS_SECRET_ACCESS_KEY")
        or existing_config.get("secret_key")
    )
    session_token = (
        body.session_token
        or os.getenv("AWS_SESSION_TOKEN")
        or existing_config.get("session_token")
    )

    if not access_key or not secret_key:
        return {}, "access_key and secret_key are required"

    conn_config: Dict = {
        "access_key": access_key.strip(),
        "secret_key": secret_key.strip(),
    }
    if session_token:
        conn_config["session_token"] = session_token.strip()
    if body.endpoint_url:
        conn_config["endpoint_url"] = body.endpoint_url.strip()
    elif existing_config.get("endpoint_url"):
        conn_config["endpoint_url"] = existing_config["endpoint_url"]
    if body.region:
        conn_config["region"] = body.region.strip()
    elif existing_config.get("region"):
        conn_config["region"] = existing_config["region"]
    if body.bucket_names is not None:
        conn_config["bucket_names"] = body.bucket_names
    elif existing_config.get("bucket_names") is not None:
        conn_config["bucket_names"] = existing_config["bucket_names"]

    return conn_config, None
