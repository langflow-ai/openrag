"""Amazon S3 / S3-compatible storage connector for OpenRAG."""

import mimetypes
import os
from datetime import datetime, timezone
from posixpath import basename
from typing import Any, Dict, List, Optional

from connectors.base import BaseConnector, ConnectorDocument, DocumentACL
from utils.logging_config import get_logger

from .auth import create_s3_client, create_s3_resource

logger = get_logger(__name__)

# Separator used in composite file IDs: "<bucket>::<key>"
_ID_SEPARATOR = "::"


def _make_file_id(bucket: str, key: str) -> str:
    return f"{bucket}{_ID_SEPARATOR}{key}"


def _split_file_id(file_id: str):
    """Split a composite file ID into (bucket, key). Raises ValueError if invalid."""
    if _ID_SEPARATOR not in file_id:
        raise ValueError(f"Invalid S3 file ID (missing separator): {file_id!r}")
    bucket, key = file_id.split(_ID_SEPARATOR, 1)
    return bucket, key


class S3Connector(BaseConnector):
    """Connector for Amazon S3 and S3-compatible object storage.

    Uses HMAC (Access Key + Secret Key) authentication. Supports AWS S3,
    MinIO, Cloudflare R2, and any service that speaks the S3 API.

    Config dict keys:
        access_key (str): Overrides AWS_ACCESS_KEY_ID.
        secret_key (str): Overrides AWS_SECRET_ACCESS_KEY.
        endpoint_url (str): Optional; overrides AWS_S3_ENDPOINT. Leave empty for AWS S3.
        region (str): Optional; overrides AWS_REGION. Default: us-east-1.
        bucket_names (list[str]): Buckets to ingest from. If empty, all accessible buckets are used.
        connection_id (str): Connection identifier used for logging.
    """

    CONNECTOR_NAME = "Amazon S3"
    CONNECTOR_DESCRIPTION = "Add knowledge from Amazon S3 or any S3-compatible storage"
    CONNECTOR_ICON = "aws-s3"

    CLIENT_ID_ENV_VAR = "AWS_ACCESS_KEY_ID"
    CLIENT_SECRET_ENV_VAR = "AWS_SECRET_ACCESS_KEY"

    def get_client_id(self) -> str:
        """Return access key from config dict, or AWS_ACCESS_KEY_ID env var as fallback."""
        val = self.config.get("access_key") or os.getenv("AWS_ACCESS_KEY_ID")
        if val:
            return val
        raise ValueError(
            "S3 credentials not set. Provide 'access_key' in the connector config "
            "or set the AWS_ACCESS_KEY_ID environment variable."
        )

    def get_client_secret(self) -> str:
        """Return secret key from config dict, or AWS_SECRET_ACCESS_KEY env var as fallback."""
        val = self.config.get("secret_key") or os.getenv("AWS_SECRET_ACCESS_KEY")
        if val:
            return val
        raise ValueError(
            "S3 credentials not set. Provide 'secret_key' in the connector config "
            "or set the AWS_SECRET_ACCESS_KEY environment variable."
        )

    def __init__(self, config: Dict[str, Any]):
        if config is None:
            config = {}
        super().__init__(config)

        self.bucket_names: List[str] = config.get("bucket_names") or []
        self.prefix: str = config.get("prefix", "")
        self.connection_id: str = config.get("connection_id", "default")

        self._resource = None  # Lazy-initialised on first use
        self._client = None

    def _get_resource(self):
        if self._resource is None:
            self._resource = create_s3_resource(self.config)
        return self._resource

    def _get_client(self):
        if self._client is None:
            self._client = create_s3_client(self.config)
        return self._client

    # ------------------------------------------------------------------
    # BaseConnector abstract method implementations
    # ------------------------------------------------------------------

    async def authenticate(self) -> bool:
        """Validate credentials by listing accessible buckets."""
        try:
            resource = self._get_resource()
            list(resource.buckets.all())
            self._authenticated = True
            logger.debug(f"S3 authenticated for connection {self.connection_id}")
            return True
        except Exception as exc:
            logger.warning(f"S3 authentication failed: {exc}")
            self._authenticated = False
            return False

    def _resolve_bucket_names(self) -> List[str]:
        """Return configured bucket names, or auto-discover all accessible buckets."""
        if self.bucket_names:
            return self.bucket_names
        try:
            resource = self._get_resource()
            buckets = [b.name for b in resource.buckets.all()]
            logger.debug("S3 auto-discovered %d bucket(s)", len(buckets))
            return buckets
        except Exception as exc:
            logger.warning(f"S3 could not auto-discover buckets: {exc}")
            return []

    async def list_files(
        self,
        page_token: Optional[str] = None,
        max_files: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """List objects across all configured (or auto-discovered) buckets.

        Uses the boto3 resource API: Bucket.objects.all() handles pagination
        internally so all objects are returned without manual continuation tokens.

        Returns:
            dict with keys:
                "files": list of file dicts (id, name, bucket, size, modified_time)
                "next_page_token": always None (SDK handles pagination internally)
        """
        resource = self._get_resource()
        files: List[Dict[str, Any]] = []
        bucket_names = self._resolve_bucket_names()

        for bucket_name in bucket_names:
            try:
                bucket = resource.Bucket(bucket_name)
                objects = (
                    bucket.objects.filter(Prefix=self.prefix)
                    if self.prefix
                    else bucket.objects.all()
                )
                for obj in objects:
                    if obj.key.endswith("/"):
                        continue
                    files.append(
                        {
                            "id": _make_file_id(bucket_name, obj.key),
                            "name": basename(obj.key) or obj.key,
                            "bucket": bucket_name,
                            "key": obj.key,
                            "size": obj.size,
                            "modified_time": obj.last_modified.isoformat()
                            if obj.last_modified
                            else None,
                        }
                    )
                    if max_files and len(files) >= max_files:
                        return {"files": files, "next_page_token": None}
            except Exception as exc:
                logger.error("Failed to list objects in S3 bucket: %s", exc)
                continue

        return {"files": files, "next_page_token": None}

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        """Download an object from S3 and return a ConnectorDocument.

        Args:
            file_id: Composite ID in the form "<bucket>::<key>".

        Returns:
            ConnectorDocument with content bytes, ACL, and metadata.
        """
        bucket_name, key = _split_file_id(file_id)
        resource = self._get_resource()

        response = resource.Object(bucket_name, key).get()
        content: bytes = response["Body"].read()

        last_modified: datetime = response.get("LastModified") or datetime.now(timezone.utc)
        size: int = response.get("ContentLength", len(content))

        # Prefer filename extension over generic S3 content-type (often application/octet-stream)
        raw_content_type = response.get("ContentType", "")
        if raw_content_type and raw_content_type != "application/octet-stream":
            mime_type: str = raw_content_type
        else:
            mime_type = mimetypes.guess_type(key)[0] or "application/octet-stream"

        filename = basename(key) or key
        acl = await self._extract_acl(bucket_name, key)

        return ConnectorDocument(
            id=file_id,
            filename=filename,
            mimetype=mime_type,
            content=content,
            source_url=f"s3://{bucket_name}/{key}",
            acl=acl,
            modified_time=last_modified,
            created_time=last_modified,  # S3 does not expose creation time
            metadata={
                "s3_bucket": bucket_name,
                "s3_key": key,
                "size": size,
            },
        )

    async def _extract_acl(self, bucket: str, key: str) -> DocumentACL:
        """Fetch object ACL from S3 and map it to DocumentACL.

        Falls back to a minimal ACL on failure (e.g. ACLs disabled on the bucket).
        """
        try:
            client = self._get_client()
            acl_response = client.get_object_acl(Bucket=bucket, Key=key)

            owner_id: str = (
                acl_response.get("Owner", {}).get("DisplayName")
                or acl_response.get("Owner", {}).get("ID")
                or ""
            )

            allowed_users: List[str] = []
            for grant in acl_response.get("Grants", []):
                grantee = grant.get("Grantee", {})
                permission = grant.get("Permission", "")
                if permission in ("FULL_CONTROL", "READ"):
                    user_id = (
                        grantee.get("DisplayName")
                        or grantee.get("ID")
                        or grantee.get("EmailAddress")
                    )
                    if user_id and user_id not in allowed_users:
                        allowed_users.append(user_id)

            return DocumentACL(
                owner=owner_id or None,
                allowed_users=allowed_users,
                allowed_groups=[],
            )
        except Exception as exc:
            logger.warning("Could not fetch S3 object ACL, using fallback: %s", exc)
            return DocumentACL(owner=None, allowed_users=[], allowed_groups=[])

    # ------------------------------------------------------------------
    # Webhook / subscription stubs (S3 event notifications are out of scope)
    # ------------------------------------------------------------------

    async def setup_subscription(self) -> str:
        """No-op: S3 event notifications are out of scope for this connector."""
        return ""

    async def handle_webhook(self, payload: Dict[str, Any]) -> List[str]:
        """No-op: webhooks are not supported in this connector version."""
        return []

    def extract_webhook_channel_id(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Optional[str]:
        return None

    async def cleanup_subscription(self, subscription_id: str) -> bool:
        """No-op: no subscription to clean up."""
        return True
