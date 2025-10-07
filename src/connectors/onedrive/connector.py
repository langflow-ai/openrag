import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import httpx

from ..base import BaseConnector, ConnectorDocument, DocumentACL
from .oauth import OneDriveOAuth

logger = logging.getLogger(__name__)


class OneDriveConnector(BaseConnector):
    """OneDrive connector using MSAL-based OAuth for authentication."""

    # Required BaseConnector class attributes
    CLIENT_ID_ENV_VAR = "MICROSOFT_GRAPH_OAUTH_CLIENT_ID"
    CLIENT_SECRET_ENV_VAR = "MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET"

    # Connector metadata
    CONNECTOR_NAME = "OneDrive"
    CONNECTOR_DESCRIPTION = "Add knowledge from OneDrive"
    CONNECTOR_ICON = "onedrive"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        logger.debug(f"OneDrive connector __init__ called with config type: {type(config)}")
        logger.debug(f"OneDrive connector __init__ config value: {config}")

        if config is None:
            logger.debug("Config was None, using empty dict")
            config = {}

        try:
            logger.debug("Calling super().__init__")
            super().__init__(config)
            logger.debug("super().__init__ completed successfully")
        except Exception as e:
            logger.error(f"super().__init__ failed: {e}")
            raise

        # Initialize with defaults that allow the connector to be listed
        self.client_id = None
        self.client_secret = None
        self.redirect_uri = config.get("redirect_uri", "http://localhost")

        # Try to get credentials, but don't fail if they're missing
        try:
            self.client_id = self.get_client_id()
            logger.debug(f"Got client_id: {self.client_id is not None}")
        except Exception as e:
            logger.debug(f"Failed to get client_id: {e}")

        try:
            self.client_secret = self.get_client_secret()
            logger.debug(f"Got client_secret: {self.client_secret is not None}")
        except Exception as e:
            logger.debug(f"Failed to get client_secret: {e}")

        # Token file setup
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        token_file = config.get("token_file") or str(project_root / "onedrive_token.json")
        Path(token_file).parent.mkdir(parents=True, exist_ok=True)

        # Only initialize OAuth if we have credentials
        if self.client_id and self.client_secret:
            connection_id = config.get("connection_id", "default")

            # Use token_file from config if provided, otherwise generate one
            if config.get("token_file"):
                oauth_token_file = config["token_file"]
            else:
                # Use a per-connection cache file to avoid collisions with other connectors
                oauth_token_file = f"onedrive_token_{connection_id}.json"

            # MSA & org both work via /common for OneDrive personal testing
            authority = "https://login.microsoftonline.com/common"

            self.oauth = OneDriveOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                token_file=oauth_token_file,
                authority=authority,
                allow_json_refresh=True,  # allows one-time migration from legacy JSON if present
            )
        else:
            self.oauth = None

        # Track subscription ID for webhooks (note: change notifications might not be available for personal accounts)
        self._subscription_id: Optional[str] = None

        # Graph API defaults
        self._graph_api_version = "v1.0"
        self._default_params = {
            "$select": "id,name,size,lastModifiedDateTime,createdDateTime,webUrl,file,folder,@microsoft.graph.downloadUrl"
        }

    @property
    def _graph_base_url(self) -> str:
        """Base URL for Microsoft Graph API calls."""
        return f"https://graph.microsoft.com/{self._graph_api_version}"

    def emit(self, doc: ConnectorDocument) -> None:
        """Emit a ConnectorDocument instance."""
        logger.debug(f"Emitting OneDrive document: {doc.id} ({doc.filename})")

    async def authenticate(self) -> bool:
        """Test authentication - BaseConnector interface."""
        logger.debug(f"OneDrive authenticate() called, oauth is None: {self.oauth is None}")
        try:
            if not self.oauth:
                logger.debug("OneDrive authentication failed: OAuth not initialized")
                self._authenticated = False
                return False

            logger.debug("Loading OneDrive credentials...")
            load_result = await self.oauth.load_credentials()
            logger.debug(f"Load credentials result: {load_result}")

            logger.debug("Checking OneDrive authentication status...")
            authenticated = await self.oauth.is_authenticated()
            logger.debug(f"OneDrive is_authenticated result: {authenticated}")

            self._authenticated = authenticated
            return authenticated
        except Exception as e:
            logger.error(f"OneDrive authentication failed: {e}")
            import traceback
            traceback.print_exc()
            self._authenticated = False
            return False

    def get_auth_url(self) -> str:
        """Get OAuth authorization URL."""
        if not self.oauth:
            raise RuntimeError("OneDrive OAuth not initialized - missing credentials")
        return self.oauth.create_authorization_url(self.redirect_uri)

    async def handle_oauth_callback(self, auth_code: str) -> Dict[str, Any]:
        """Handle OAuth callback."""
        if not self.oauth:
            raise RuntimeError("OneDrive OAuth not initialized - missing credentials")
        try:
            success = await self.oauth.handle_authorization_callback(auth_code, self.redirect_uri)
            if success:
                self._authenticated = True
                return {"status": "success"}
            else:
                raise ValueError("OAuth callback failed")
        except Exception as e:
            logger.error(f"OAuth callback failed: {e}")
            raise

    def sync_once(self) -> None:
        """
        Perform a one-shot sync of OneDrive files and emit documents.
        """
        import asyncio

        async def _async_sync():
            try:
                file_list = await self.list_files(max_files=1000)
                files = file_list.get("files", [])
                for file_info in files:
                    try:
                        file_id = file_info.get("id")
                        if not file_id:
                            continue
                        doc = await self.get_file_content(file_id)
                        self.emit(doc)
                    except Exception as e:
                        logger.error(f"Failed to sync OneDrive file {file_info.get('name', 'unknown')}: {e}")
                        continue
            except Exception as e:
                logger.error(f"OneDrive sync_once failed: {e}")
                raise

        if hasattr(asyncio, 'run'):
            asyncio.run(_async_sync())
        else:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(_async_sync())

    async def setup_subscription(self) -> str:
        """
        Set up real-time subscription for file changes.
        NOTE: Change notifications may not be available for personal OneDrive accounts.
        """
        webhook_url = self.config.get('webhook_url')
        if not webhook_url:
            logger.warning("No webhook URL configured, skipping OneDrive subscription setup")
            return "no-webhook-configured"

        try:
            if not await self.authenticate():
                raise RuntimeError("OneDrive authentication failed during subscription setup")

            token = self.oauth.get_access_token()

            # For OneDrive personal we target the user's drive
            resource = "/me/drive/root"

            subscription_data = {
                "changeType": "created,updated,deleted",
                "notificationUrl": f"{webhook_url}/webhook/onedrive",
                "resource": resource,
                "expirationDateTime": self._get_subscription_expiry(),
                "clientState": "onedrive_personal",
            }

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            url = f"{self._graph_base_url}/subscriptions"

            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=subscription_data, headers=headers, timeout=30)
                response.raise_for_status()

                result = response.json()
                subscription_id = result.get("id")

                if subscription_id:
                    self._subscription_id = subscription_id
                    logger.info(f"OneDrive subscription created: {subscription_id}")
                    return subscription_id
                else:
                    raise ValueError("No subscription ID returned from Microsoft Graph")

        except Exception as e:
            logger.error(f"Failed to setup OneDrive subscription: {e}")
            raise

    def _get_subscription_expiry(self) -> str:
        """Get subscription expiry time (Graph caps duration; often <= 3 days)."""
        from datetime import datetime, timedelta
        expiry = datetime.utcnow() + timedelta(days=3)
        return expiry.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    async def list_files(
        self,
        page_token: Optional[str] = None,
        max_files: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """List files from OneDrive using Microsoft Graph."""
        try:
            if not await self.authenticate():
                raise RuntimeError("OneDrive authentication failed during file listing")

            files: List[Dict[str, Any]] = []
            max_files_value = max_files if max_files is not None else 100

            base_url = f"{self._graph_base_url}/me/drive/root/children"

            params = dict(self._default_params)
            params["$top"] = str(max_files_value)

            if page_token:
                params["$skiptoken"] = page_token

            response = await self._make_graph_request(base_url, params=params)
            data = response.json()

            items = data.get("value", [])
            for item in items:
                if item.get("file"):  # include files only
                    files.append({
                        "id": item.get("id", ""),
                        "name": item.get("name", ""),
                        "path": f"/drive/items/{item.get('id')}",
                        "size": int(item.get("size", 0)),
                        "modified": item.get("lastModifiedDateTime"),
                        "created": item.get("createdDateTime"),
                        "mime_type": item.get("file", {}).get("mimeType", self._get_mime_type(item.get("name", ""))),
                        "url": item.get("webUrl", ""),
                        "download_url": item.get("@microsoft.graph.downloadUrl"),
                    })

            # Next page
            next_page_token = None
            next_link = data.get("@odata.nextLink")
            if next_link:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(next_link)
                query_params = parse_qs(parsed.query)
                if "$skiptoken" in query_params:
                    next_page_token = query_params["$skiptoken"][0]

            return {"files": files, "next_page_token": next_page_token}

        except Exception as e:
            logger.error(f"Failed to list OneDrive files: {e}")
            return {"files": [], "next_page_token": None}

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        """Get file content and metadata."""
        try:
            if not await self.authenticate():
                raise RuntimeError("OneDrive authentication failed during file content retrieval")

            file_metadata = await self._get_file_metadata_by_id(file_id)
            if not file_metadata:
                raise ValueError(f"File not found: {file_id}")

            download_url = file_metadata.get("download_url")
            if download_url:
                content = await self._download_file_from_url(download_url)
            else:
                content = await self._download_file_content(file_id)

            acl = DocumentACL(
                owner="",
                user_permissions={},
                group_permissions={},
            )

            modified_time = self._parse_graph_date(file_metadata.get("modified"))
            created_time = self._parse_graph_date(file_metadata.get("created"))

            return ConnectorDocument(
                id=file_id,
                filename=file_metadata.get("name", ""),
                mimetype=file_metadata.get("mime_type", "application/octet-stream"),
                content=content,
                source_url=file_metadata.get("url", ""),
                acl=acl,
                modified_time=modified_time,
                created_time=created_time,
                metadata={
                    "onedrive_path": file_metadata.get("path", ""),
                    "size": file_metadata.get("size", 0),
                },
            )

        except Exception as e:
            logger.error(f"Failed to get OneDrive file content {file_id}: {e}")
            raise

    async def _get_file_metadata_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file metadata by ID using Graph API."""
        try:
            url = f"{self._graph_base_url}/me/drive/items/{file_id}"
            params = dict(self._default_params)

            response = await self._make_graph_request(url, params=params)
            item = response.json()

            if item.get("file"):
                return {
                    "id": file_id,
                    "name": item.get("name", ""),
                    "path": f"/drive/items/{file_id}",
                    "size": int(item.get("size", 0)),
                    "modified": item.get("lastModifiedDateTime"),
                    "created": item.get("createdDateTime"),
                    "mime_type": item.get("file", {}).get("mimeType", self._get_mime_type(item.get("name", ""))),
                    "url": item.get("webUrl", ""),
                    "download_url": item.get("@microsoft.graph.downloadUrl"),
                }

            return None

        except Exception as e:
            logger.error(f"Failed to get file metadata for {file_id}: {e}")
            return None

    async def _download_file_content(self, file_id: str) -> bytes:
        """Download file content by file ID using Graph API."""
        try:
            url = f"{self._graph_base_url}/me/drive/items/{file_id}/content"
            token = self.oauth.get_access_token()
            headers = {"Authorization": f"Bearer {token}"}

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=60)
                response.raise_for_status()
                return response.content

        except Exception as e:
            logger.error(f"Failed to download file content for {file_id}: {e}")
            raise

    async def _download_file_from_url(self, download_url: str) -> bytes:
        """Download file content from direct download URL."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(download_url, timeout=60)
                response.raise_for_status()
                return response.content
        except Exception as e:
            logger.error(f"Failed to download from URL {download_url}: {e}")
            raise

    def _parse_graph_date(self, date_str: Optional[str]) -> datetime:
        """Parse Microsoft Graph date string to datetime."""
        if not date_str:
            return datetime.now()
        try:
            if date_str.endswith('Z'):
                return datetime.fromisoformat(date_str[:-1]).replace(tzinfo=None)
            else:
                return datetime.fromisoformat(date_str.replace('T', ' '))
        except (ValueError, AttributeError):
            return datetime.now()

    async def _make_graph_request(self, url: str, method: str = "GET",
                                  data: Optional[Dict] = None, params: Optional[Dict] = None) -> httpx.Response:
        """Make authenticated API request to Microsoft Graph."""
        token = self.oauth.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            if method.upper() == "GET":
                response = await client.get(url, headers=headers, params=params, timeout=30)
            elif method.upper() == "POST":
                response = await client.post(url, headers=headers, json=data, timeout=30)
            elif method.upper() == "DELETE":
                response = await client.delete(url, headers=headers, timeout=30)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response

    def _get_mime_type(self, filename: str) -> str:
        """Get MIME type based on file extension."""
        import mimetypes
        mime_type, _ = mimetypes.guess_type(filename)
        return mime_type or "application/octet-stream"

    # Webhook methods - BaseConnector interface
    def handle_webhook_validation(self, request_method: str,
                                  headers: Dict[str, str],
                                  query_params: Dict[str, str]) -> Optional[str]:
        """Handle webhook validation (Graph API specific)."""
        if request_method == "POST" and "validationToken" in query_params:
            return query_params["validationToken"]
        return None

    def extract_webhook_channel_id(self, payload: Dict[str, Any],
                                   headers: Dict[str, str]) -> Optional[str]:
        """Extract channel/subscription ID from webhook payload."""
        notifications = payload.get("value", [])
        if notifications:
            return notifications[0].get("subscriptionId")
        return None

    async def handle_webhook(self, payload: Dict[str, Any]) -> List[str]:
        """Handle webhook notification and return affected file IDs."""
        affected_files: List[str] = []
        notifications = payload.get("value", [])
        for notification in notifications:
            resource = notification.get("resource")
            if resource and "/drive/items/" in resource:
                file_id = resource.split("/drive/items/")[-1]
                affected_files.append(file_id)
        return affected_files

    async def cleanup_subscription(self, subscription_id: str) -> bool:
        """Clean up subscription - BaseConnector interface."""
        if subscription_id == "no-webhook-configured":
            logger.info("No subscription to cleanup (webhook was not configured)")
            return True

        try:
            if not await self.authenticate():
                logger.error("OneDrive authentication failed during subscription cleanup")
                return False

            token = self.oauth.get_access_token()
            headers = {"Authorization": f"Bearer {token}"}

            url = f"{self._graph_base_url}/subscriptions/{subscription_id}"

            async with httpx.AsyncClient() as client:
                response = await client.delete(url, headers=headers, timeout=30)

                if response.status_code in [200, 204, 404]:
                    logger.info(f"OneDrive subscription {subscription_id} cleaned up successfully")
                    return True
                else:
                    logger.warning(f"Unexpected response cleaning up subscription: {response.status_code}")
                    return False

        except Exception as e:
            logger.error(f"Failed to cleanup OneDrive subscription {subscription_id}: {e}")
            return False
