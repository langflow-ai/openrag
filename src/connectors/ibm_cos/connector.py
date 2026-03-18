"""IBM Cloud Object Storage connector for OpenRAG."""

import mimetypes
import os
from datetime import datetime, timezone
from posixpath import basename
from typing import Any, Dict, List, Optional

from connectors.base import BaseConnector, ConnectorDocument, DocumentACL
from utils.logging_config import get_logger

from .auth import create_ibm_cos_client, create_ibm_cos_resource

logger = get_logger(__name__)

# Separator used in composite file IDs: "<bucket>::<key>"
_ID_SEPARATOR = "::"


def _make_file_id(bucket: str, key: str) -> str:
    return f"{bucket}{_ID_SEPARATOR}{key}"


def _split_file_id(file_id: str):
    """Split a composite file ID into (bucket, key). Raises ValueError if invalid."""
    if _ID_SEPARATOR not in file_id:
        raise ValueError(f"Invalid IBM COS file ID (missing separator): {file_id!r}")
    bucket, key = file_id.split(_ID_SEPARATOR, 1)
    return bucket, key


class IBMCOSConnector(BaseConnector):
    """Connector for IBM Cloud Object Storage.

    Supports IAM (API key) and HMAC credential modes. Credentials are read
    from the connector config dict first, then from environment variables.

    Config dict keys:
        bucket_names (list[str]): Buckets to ingest from. Required.
        prefix (str): Optional object key prefix filter.
        endpoint_url (str): Overrides IBM_COS_ENDPOINT.
        api_key (str): Overrides IBM_COS_API_KEY.
        service_instance_id (str): Overrides IBM_COS_SERVICE_INSTANCE_ID.
        hmac_access_key (str): HMAC mode – overrides IBM_COS_HMAC_ACCESS_KEY_ID.
        hmac_secret_key (str): HMAC mode – overrides IBM_COS_HMAC_SECRET_ACCESS_KEY.
        connection_id (str): Connection identifier used for logging.
    """

    CONNECTOR_NAME = "IBM Cloud Object Storage"
    CONNECTOR_DESCRIPTION = "Add knowledge from IBM Cloud Object Storage"
    CONNECTOR_ICON = "ibm-cos"

    # BaseConnector uses these to check env-var availability for IAM mode.
    # HMAC-only setups will show as "unavailable" in the UI but can still be
    # used when credentials are supplied in the config dict directly.
    CLIENT_ID_ENV_VAR = "IBM_COS_API_KEY"
    CLIENT_SECRET_ENV_VAR = "IBM_COS_SERVICE_INSTANCE_ID"

    def get_client_id(self) -> str:
        """Return IAM API key, or HMAC access key ID as fallback."""
        val = (
            self.config.get("api_key")
            or self.config.get("hmac_access_key")
            or os.getenv("IBM_COS_API_KEY")
            or os.getenv("IBM_COS_HMAC_ACCESS_KEY_ID")
        )
        if val:
            return val
        raise ValueError(
            "IBM COS credentials not set. Provide IBM_COS_API_KEY (IAM) "
            "or IBM_COS_HMAC_ACCESS_KEY_ID (HMAC)."
        )

    def get_client_secret(self) -> str:
        """Return IAM service instance ID, or HMAC secret key as fallback."""
        val = (
            self.config.get("service_instance_id")
            or self.config.get("hmac_secret_key")
            or os.getenv("IBM_COS_SERVICE_INSTANCE_ID")
            or os.getenv("IBM_COS_HMAC_SECRET_ACCESS_KEY")
        )
        if val:
            return val
        raise ValueError(
            "IBM COS credentials not set. Provide IBM_COS_SERVICE_INSTANCE_ID (IAM) "
            "or IBM_COS_HMAC_SECRET_ACCESS_KEY (HMAC)."
        )

    def __init__(self, config: Dict[str, Any]):
        if config is None:
            config = {}
        super().__init__(config)

        self.bucket_names: List[str] = config.get("bucket_names") or []
        self.prefix: str = config.get("prefix", "")
        self.connection_id: str = config.get("connection_id", "default")

        # Resolved service instance ID used as ACL owner fallback
        self._service_instance_id: str = (
            config.get("service_instance_id")
            or os.getenv("IBM_COS_SERVICE_INSTANCE_ID", "")
        )

        self._handle = None  # Lazy-initialised on first use
        # IAM mode uses ibm_boto3.client to avoid internal service-instance
        # discovery calls that cause XML-parse errors against the real IBM COS API.
        # HMAC mode uses ibm_boto3.resource (confirmed working with MinIO and S3).
        self._is_hmac: bool = (config.get("auth_mode", "iam") == "hmac")

    def _get_handle(self):
        """Return (and cache) the appropriate boto3 handle for the configured auth mode.

        - HMAC → ibm_boto3.resource  (S3-compatible, works with MinIO)
        - IAM  → ibm_boto3.client   (avoids ibm_botocore service-discovery calls
                                      that break against the real IBM COS API)
        """
        if self._handle is None:
            if self._is_hmac:
                self._handle = create_ibm_cos_resource(self.config)
            else:
                self._handle = create_ibm_cos_client(self.config)
        return self._handle

    # ------------------------------------------------------------------
    # BaseConnector abstract method implementations
    # ------------------------------------------------------------------

    async def authenticate(self) -> bool:
        """Validate credentials by listing buckets on the COS service."""
        try:
            handle = self._get_handle()
            if self._is_hmac:
                list(handle.buckets.all())        # resource API
            else:
                handle.list_buckets()             # client API
            self._authenticated = True
            logger.debug(f"IBM COS authenticated for connection {self.connection_id}")
            return True
        except Exception as exc:
            logger.warning(f"IBM COS authentication failed: {exc}")
            self._authenticated = False
            return False

    def _resolve_bucket_names(self) -> List[str]:
        """Return configured bucket names, or auto-discover all accessible buckets."""
        if self.bucket_names:
            return self.bucket_names
        try:
            handle = self._get_handle()
            if self._is_hmac:
                buckets = [b.name for b in handle.buckets.all()]
            else:
                resp = handle.list_buckets()
                buckets = [b["Name"] for b in resp.get("Buckets", [])]
            logger.debug("IBM COS auto-discovered %d bucket(s)", len(buckets))
            return buckets
        except Exception as exc:
            logger.warning(f"IBM COS could not auto-discover buckets: {exc}")
            return []

    async def list_files(
        self,
        page_token: Optional[str] = None,
        max_files: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """List objects across all configured (or auto-discovered) buckets.

        Uses the ibm_boto3 resource API: Bucket.objects.all() handles pagination
        internally so all objects are returned without manual continuation tokens.

        If no bucket_names are configured, all accessible buckets are used.

        Returns:
            dict with keys:
                "files": list of file dicts (id, name, bucket, size, modified_time)
                "next_page_token": always None (SDK handles pagination internally)
        """
        handle = self._get_handle()
        files: List[Dict[str, Any]] = []
        bucket_names = self._resolve_bucket_names()

        for bucket_name in bucket_names:
            try:
                if self._is_hmac:
                    # resource API: Bucket.objects.all() handles pagination internally
                    bucket = handle.Bucket(bucket_name)
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
                else:
                    # client API: list_objects_v2 with manual pagination
                    kwargs: Dict[str, Any] = {"Bucket": bucket_name}
                    if self.prefix:
                        kwargs["Prefix"] = self.prefix
                    while True:
                        resp = handle.list_objects_v2(**kwargs)
                        for obj in resp.get("Contents", []):
                            key = obj["Key"]
                            if key.endswith("/"):
                                continue
                            files.append(
                                {
                                    "id": _make_file_id(bucket_name, key),
                                    "name": basename(key) or key,
                                    "bucket": bucket_name,
                                    "key": key,
                                    "size": obj.get("Size", 0),
                                    "modified_time": obj["LastModified"].isoformat()
                                    if obj.get("LastModified")
                                    else None,
                                }
                            )
                            if max_files and len(files) >= max_files:
                                return {"files": files, "next_page_token": None}
                        if resp.get("IsTruncated"):
                            kwargs["ContinuationToken"] = resp["NextContinuationToken"]
                        else:
                            break

            except Exception as exc:
                logger.error("Failed to list objects in IBM COS bucket: %s", exc)
                continue

        return {"files": files, "next_page_token": None}

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        """Download an object from IBM COS and return a ConnectorDocument.

        Uses the ibm_boto3 resource API: Object.get() downloads content and
        returns all metadata (ContentType, ContentLength, LastModified) in one call.

        Args:
            file_id: Composite ID in the form "<bucket>::<key>".

        Returns:
            ConnectorDocument with content bytes, ACL, and metadata.
        """
        bucket_name, key = _split_file_id(file_id)
        handle = self._get_handle()

        # Both client.get_object() and resource.Object().get() return the same
        # response dict: Body stream + ContentType, ContentLength, LastModified.
        if self._is_hmac:
            response = handle.Object(bucket_name, key).get()   # resource
        else:
            response = handle.get_object(Bucket=bucket_name, Key=key)  # client
        content: bytes = response["Body"].read()

        last_modified: datetime = response.get("LastModified") or datetime.now(timezone.utc)
        size: int = response.get("ContentLength", len(content))

        # MIME type detection: prefer filename extension over generic S3 content-type.
        # IBM COS often stores "application/octet-stream" for all objects regardless
        # of their real type, so we treat that as "unknown" and fall back to the
        # extension-based guess which is more reliable for named files.
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
            source_url=f"cos://{bucket_name}/{key}",
            acl=acl,
            modified_time=last_modified,
            created_time=last_modified,  # IBM COS does not expose creation time
            metadata={
                "ibm_cos_bucket": bucket_name,
                "ibm_cos_key": key,
                "size": size,
            },
        )

    async def _extract_acl(self, bucket: str, key: str) -> DocumentACL:
        """Fetch object ACL from IBM COS and map it to DocumentACL.

        Falls back to a minimal ACL (owner = service instance ID) on failure.
        """
        try:
            handle = self._get_handle()
            # For resource (HMAC), access the underlying client via meta.client.
            # For client (IAM), call directly.
            client = handle.meta.client if self._is_hmac else handle
            acl_response = client.get_object_acl(Bucket=bucket, Key=key)

            owner_id: str = (
                acl_response.get("Owner", {}).get("DisplayName")
                or acl_response.get("Owner", {}).get("ID")
                or self._service_instance_id
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
                owner=owner_id,
                allowed_users=allowed_users,
                allowed_groups=[],
            )
        except Exception as exc:
            logger.warning("Could not fetch IBM COS object ACL, using fallback: %s", exc)
            return DocumentACL(
                owner=self._service_instance_id or None,
                allowed_users=[],
                allowed_groups=[],
            )

    # ------------------------------------------------------------------
    # Webhook / subscription (stub — IBM COS events require IBM Event
    # Notifications service; not in scope for this connector version)
    # ------------------------------------------------------------------

    async def setup_subscription(self) -> str:
        """No-op: IBM COS event notifications are out of scope for this connector."""
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




if __name__ == "__main__":
    connector = IBMCOSConnector({})
    print(connector.authenticate())
    print(connector.list_files())
    # print(connector.get_file_content("test_cos.py"))