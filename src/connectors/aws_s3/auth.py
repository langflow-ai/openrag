"""Amazon S3 / S3-compatible storage authentication and client factory."""

import os
from typing import Any, Dict, Optional

from utils.logging_config import get_logger

logger = get_logger(__name__)

_DEFAULT_REGION = "us-east-1"


def _resolve_credentials(config: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve S3 credentials from config dict with environment variable fallback.

    Resolution order for each value: config dict → environment variable → default.

    Raises:
        ValueError: If access_key or secret_key cannot be resolved.
    """
    access_key: Optional[str] = config.get("access_key") or os.getenv("AWS_ACCESS_KEY_ID")
    secret_key: Optional[str] = config.get("secret_key") or os.getenv("AWS_SECRET_ACCESS_KEY")
    session_token: Optional[str] = (
        config.get("session_token") or os.getenv("AWS_SESSION_TOKEN") or None
    )

    if not access_key or not secret_key:
        raise ValueError(
            "S3 credentials are required. Provide 'access_key' and 'secret_key' in the "
            "connector config, or set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY env vars."
        )

    # endpoint_url is optional — only inject when non-empty (real AWS users don't set it)
    endpoint_url: Optional[str] = config.get("endpoint_url") or os.getenv("AWS_S3_ENDPOINT") or None

    region: str = config.get("region") or os.getenv("AWS_REGION") or _DEFAULT_REGION

    return {
        "access_key": access_key,
        "secret_key": secret_key,
        "session_token": session_token,
        "endpoint_url": endpoint_url,
        "region": region,
    }


def _build_boto3_kwargs(creds: Dict[str, Any]) -> Dict[str, Any]:
    """Build the keyword arguments for boto3.resource / boto3.client."""
    kwargs: Dict[str, Any] = {
        "aws_access_key_id": creds["access_key"],
        "aws_secret_access_key": creds["secret_key"],
        "region_name": creds["region"],
    }
    if creds.get("session_token"):
        kwargs["aws_session_token"] = creds["session_token"]
    if creds["endpoint_url"]:
        kwargs["endpoint_url"] = creds["endpoint_url"]
    return kwargs


def _normalize_bucket_names(bucket_names: Optional[list[str]]) -> list[str]:
    if not bucket_names:
        return []
    return [bucket.strip() for bucket in bucket_names if bucket and bucket.strip()]


def validate_s3_access(
    config: Dict[str, Any],
    bucket_names: Optional[list[str]] = None,
) -> list[str]:
    """Validate S3 access and return the accessible bucket names.

    When bucket names are supplied, validate them with ``HeadBucket`` so
    bucket-scoped IAM policies work without ``s3:ListAllMyBuckets``.
    Otherwise, fall back to ``ListBuckets``.
    """
    client = create_s3_client(config)
    requested_buckets = _normalize_bucket_names(bucket_names or config.get("bucket_names"))

    if requested_buckets:
        for bucket_name in requested_buckets:
            client.head_bucket(Bucket=bucket_name)
        return requested_buckets

    response = client.list_buckets()
    return [bucket["Name"] for bucket in response.get("Buckets", []) if bucket.get("Name")]


def describe_s3_error(
    exc: Exception,
    bucket_names: Optional[list[str]] = None,
) -> str:
    """Return a user-facing error message for a boto3/botocore S3 exception."""
    requested_buckets = _normalize_bucket_names(bucket_names)
    error = getattr(exc, "response", {}).get("Error", {})
    error_code = error.get("Code")
    raw_message = (error.get("Message") or str(exc) or "").strip()

    if error_code == "AccessDenied":
        if requested_buckets:
            return (
                "Access denied for the configured bucket(s): "
                f"{', '.join(requested_buckets)}. Confirm the credentials have "
                "bucket and object read access."
            )
        return (
            "Access denied while listing buckets. This AWS principal may be missing "
            "`s3:ListAllMyBuckets`. Enter specific bucket names to validate a "
            "bucket-scoped policy instead."
        )

    if error_code in {"InvalidAccessKeyId", "SignatureDoesNotMatch"}:
        return (
            "AWS rejected the provided credentials. Check the access key, secret key, "
            "session token, region, and endpoint URL."
        )

    if error_code in {"ExpiredToken", "InvalidToken"}:
        return "The AWS session token is missing, invalid, or expired."

    if error_code in {"AuthorizationHeaderMalformed", "PermanentRedirect"}:
        return "The configured region or endpoint URL does not match the target bucket."

    if error_code == "NoSuchBucket" and requested_buckets:
        return (
            "One or more configured buckets do not exist or are not accessible: "
            f"{', '.join(requested_buckets)}."
        )

    if "Could not connect to the endpoint URL" in raw_message:
        return "Could not reach the S3 endpoint. Check the endpoint URL, region, and network."

    return raw_message or "Could not connect to S3 with the provided configuration."


def create_s3_resource(config: Dict[str, Any]):
    """Return a boto3 S3 resource (high-level API) for bucket/object access.

    Works with AWS S3, MinIO, Cloudflare R2, and any S3-compatible service.
    """
    try:
        import boto3
    except ImportError as exc:
        raise ImportError(
            "boto3 is required for the S3 connector. "
            "Install it with: pip install boto3"
        ) from exc

    creds = _resolve_credentials(config)
    kwargs = _build_boto3_kwargs(creds)
    logger.debug("Creating S3 resource with HMAC authentication (boto3)")
    return boto3.resource("s3", **kwargs)


def create_s3_client(config: Dict[str, Any]):
    """Return a boto3 S3 low-level client.

    Used for operations such as list_buckets() and get_object_acl().
    """
    try:
        import boto3
    except ImportError as exc:
        raise ImportError(
            "boto3 is required for the S3 connector. "
            "Install it with: pip install boto3"
        ) from exc

    creds = _resolve_credentials(config)
    kwargs = _build_boto3_kwargs(creds)
    logger.debug("Creating S3 client with HMAC authentication (boto3)")
    return boto3.client("s3", **kwargs)
