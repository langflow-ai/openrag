"""IBM Cloud Object Storage authentication and client factory."""

import os
from typing import Dict, Any

from utils.logging_config import get_logger

logger = get_logger(__name__)

# IAM auth endpoint default
_DEFAULT_AUTH_ENDPOINT = "https://iam.cloud.ibm.com/identity/token"


def _resolve_credentials(config: Dict[str, Any]):
    """Resolve IBM COS credentials from config dict → environment variable fallback.

    Returns a dict with the resolved values needed to build a boto3 client/resource.
    Raises ValueError if neither IAM nor HMAC credentials are available.
    """
    endpoint_url = config.get("endpoint_url") or os.getenv("IBM_COS_ENDPOINT")
    if not endpoint_url:
        raise ValueError(
            "IBM COS endpoint URL is required. Set IBM_COS_ENDPOINT or provide "
            "'endpoint_url' in the connector config."
        )

    api_key = config.get("api_key") or os.getenv("IBM_COS_API_KEY")
    service_instance_id = (
        config.get("service_instance_id") or os.getenv("IBM_COS_SERVICE_INSTANCE_ID")
    )
    hmac_access_key = (
        config.get("hmac_access_key") or os.getenv("IBM_COS_HMAC_ACCESS_KEY_ID")
    )
    hmac_secret_key = (
        config.get("hmac_secret_key") or os.getenv("IBM_COS_HMAC_SECRET_ACCESS_KEY")
    )
    auth_endpoint = (
        config.get("auth_endpoint")
        or os.getenv("IBM_COS_AUTH_ENDPOINT")
        or _DEFAULT_AUTH_ENDPOINT
    )

    return {
        "endpoint_url": endpoint_url,
        "api_key": api_key,
        "service_instance_id": service_instance_id,
        "hmac_access_key": hmac_access_key,
        "hmac_secret_key": hmac_secret_key,
        "auth_endpoint": auth_endpoint,
    }


def _build_resource(config: Dict[str, Any], creds: Dict[str, Any]):
    """Build an S3-compatible resource using resolved credentials.

    HMAC mode uses standard boto3 (no IBM-specific calls, pure S3 protocol).
    IAM mode uses ibm_boto3 with OAuth signature.
    """
    auth_mode = config.get("auth_mode", "iam")

    if auth_mode == "hmac":
        if not (creds["hmac_access_key"] and creds["hmac_secret_key"]):
            raise ValueError(
                "HMAC mode requires hmac_access_key and hmac_secret_key."
            )
        try:
            import boto3
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for IBM COS HMAC mode. "
                "Install it with: pip install boto3"
            ) from exc
        logger.debug("Creating IBM COS resource with HMAC authentication (boto3)")
        return boto3.resource(
            "s3",
            aws_access_key_id=creds["hmac_access_key"],
            aws_secret_access_key=creds["hmac_secret_key"],
            endpoint_url=creds["endpoint_url"],
        )

    # IAM mode (default) — requires ibm_boto3 for OAuth token handling
    try:
        import ibm_boto3
        from ibm_botocore.client import Config
    except ImportError as exc:
        raise ImportError(
            "ibm-cos-sdk is required for IBM COS IAM mode. "
            "Install it with: pip install ibm-cos-sdk"
        ) from exc
    if not (creds["api_key"] and creds["service_instance_id"]):
        raise ValueError(
            "IAM mode requires api_key and service_instance_id."
        )
    logger.debug("Creating IBM COS resource with IAM authentication (ibm_boto3)")
    return ibm_boto3.resource(
        "s3",
        ibm_api_key_id=creds["api_key"],
        ibm_service_instance_id=creds["service_instance_id"],
        ibm_auth_endpoint=creds["auth_endpoint"],
        config=Config(signature_version="oauth"),
        endpoint_url=creds["endpoint_url"],
    )


def _build_client(config: Dict[str, Any], creds: Dict[str, Any]):
    """Build an S3-compatible client using resolved credentials.

    HMAC mode uses standard boto3 (no IBM-specific calls, pure S3 protocol).
    IAM mode uses ibm_boto3 with OAuth signature.
    """
    auth_mode = config.get("auth_mode", "iam")

    if auth_mode == "hmac":
        if not (creds["hmac_access_key"] and creds["hmac_secret_key"]):
            raise ValueError(
                "HMAC mode requires hmac_access_key and hmac_secret_key."
            )
        try:
            import boto3
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for IBM COS HMAC mode. "
                "Install it with: pip install boto3"
            ) from exc
        logger.debug("Creating IBM COS client with HMAC authentication (boto3)")
        return boto3.client(
            "s3",
            aws_access_key_id=creds["hmac_access_key"],
            aws_secret_access_key=creds["hmac_secret_key"],
            endpoint_url=creds["endpoint_url"],
        )

    # IAM mode (default) — requires ibm_boto3 for OAuth token handling
    try:
        import ibm_boto3
        from ibm_botocore.client import Config
    except ImportError as exc:
        raise ImportError(
            "ibm-cos-sdk is required for IBM COS IAM mode. "
            "Install it with: pip install ibm-cos-sdk"
        ) from exc
    if not (creds["api_key"] and creds["service_instance_id"]):
        raise ValueError(
            "IAM mode requires api_key and service_instance_id."
        )
    logger.debug("Creating IBM COS client with IAM authentication (ibm_boto3)")
    return ibm_boto3.client(
        "s3",
        ibm_api_key_id=creds["api_key"],
        ibm_service_instance_id=creds["service_instance_id"],
        ibm_auth_endpoint=creds["auth_endpoint"],
        config=Config(signature_version="oauth"),
        endpoint_url=creds["endpoint_url"],
    )


def create_ibm_cos_resource(config: Dict[str, Any]):
    """Return an S3 resource handle (high-level API).

    HMAC mode returns a standard boto3.resource (pure S3, no IBM discovery calls).
    IAM mode returns an ibm_boto3.resource (OAuth token handling).

    Auth mode is determined by config["auth_mode"]:
    - "iam"  (default): IBM_COS_API_KEY + IBM_COS_SERVICE_INSTANCE_ID
    - "hmac": IBM_COS_HMAC_ACCESS_KEY_ID + IBM_COS_HMAC_SECRET_ACCESS_KEY

    Resolution order for each credential: config dict → environment variable.
    """
    creds = _resolve_credentials(config)
    return _build_resource(config, creds)


def create_ibm_cos_client(config: Dict[str, Any]):
    """Return an S3 low-level client.

    HMAC mode returns a standard boto3.client (pure S3, no IBM discovery calls).
    IAM mode returns an ibm_boto3.client (OAuth token handling).

    Used by API endpoints that need raw client operations (e.g. get_object_acl).
    For bucket/object listing and download, prefer create_ibm_cos_resource().
    """
    creds = _resolve_credentials(config)
    return _build_client(config, creds)
