"""Support helpers for IBM COS API endpoints.

Contains pure (non-async) business logic for credential resolution and
config dict construction, keeping the route handlers thin.
"""

import os
from typing import Dict, Optional, Tuple

from .models import IBMCOSConfigureBody


def build_ibm_cos_config(
    body: IBMCOSConfigureBody,
    existing_config: Dict,
) -> Tuple[Dict, Optional[str]]:
    """Resolve IBM COS credentials and build the connection config dict.

    Resolution order for each credential: request body → environment variable
    → existing connection config.

    Returns:
        (conn_config, None)  on success
        ({}, error_message)  on validation failure
    """
    conn_config: Dict = {
        "auth_mode": body.auth_mode,
        "endpoint_url": body.endpoint,
    }

    if body.auth_mode == "iam":
        api_key = (
            body.api_key
            or os.getenv("IBM_COS_API_KEY")
            or existing_config.get("api_key")
        )
        svc_id = (
            body.service_instance_id
            or os.getenv("IBM_COS_SERVICE_INSTANCE_ID")
            or existing_config.get("service_instance_id")
        )
        if not api_key or not svc_id:
            return {}, "IAM mode requires api_key and service_instance_id"
        conn_config["api_key"] = api_key
        conn_config["service_instance_id"] = svc_id
        if body.auth_endpoint:
            conn_config["auth_endpoint"] = body.auth_endpoint
    else:
        # HMAC mode
        hmac_access = (
            body.hmac_access_key
            or os.getenv("IBM_COS_HMAC_ACCESS_KEY_ID")
            or existing_config.get("hmac_access_key")
        )
        hmac_secret = (
            body.hmac_secret_key
            or os.getenv("IBM_COS_HMAC_SECRET_ACCESS_KEY")
            or existing_config.get("hmac_secret_key")
        )
        if not hmac_access or not hmac_secret:
            return {}, "HMAC mode requires hmac_access_key and hmac_secret_key"
        conn_config["hmac_access_key"] = hmac_access
        conn_config["hmac_secret_key"] = hmac_secret

    if body.bucket_names is not None:
        conn_config["bucket_names"] = body.bucket_names

    return conn_config, None
