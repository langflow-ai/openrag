import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from urllib.parse import urlparse
import httpx

from ..base import BaseConnector, ConnectorDocument, DocumentACL
from .oauth import OneDriveOAuth

logger = logging.getLogger(__name__)


class OneDriveConnector(BaseConnector):
    """OneDrive connector using MSAL-based OAuth for authentication."""

    # Required BaseConnector class attributes
    CLIENT_ID_ENV_VAR = "MICROSOFT_GRAPH_OAUTH_CLIENT_ID"
    CLIENT_SECRET_ENV_VAR = "MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET"  # pragma: allowlist secret

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
        self._base_url = config.get("base_url")  # Generic URL field for OneDrive/SharePoint domain
        logger.debug(f"OneDrive connector initialized with base_url from config: {self._base_url}")

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

        # Token file setup - use data/ directory for persistence
        token_file = config.get("token_file") or "data/onedrive_token.json"
        Path(token_file).parent.mkdir(parents=True, exist_ok=True)

        # Only initialize OAuth if we have credentials
        if self.client_id and self.client_secret:
            connection_id = config.get("connection_id", "default")

            # Use token_file from config if provided, otherwise generate one
            if config.get("token_file"):
                oauth_token_file = config["token_file"]
            else:
                # Use a per-connection cache file to avoid collisions with other connectors
                oauth_token_file = f"data/onedrive_token_{connection_id}.json"

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
        
        # Selective sync support (similar to Google Drive)
        self.cfg = type('OneDriveConfig', (), {
            'file_ids': config.get('file_ids') or config.get('selected_files') or config.get('selected_file_ids'),
            'folder_ids': config.get('folder_ids') or config.get('selected_folders') or config.get('selected_folder_ids'),
        })()
        
        # Cache for file metadata including download URLs
        # This allows direct download without Graph API for sharing IDs
        self._file_infos: Dict[str, Dict[str, Any]] = {}

    @property
    def _graph_base_url(self) -> str:
        """Base URL for Microsoft Graph API calls."""
        return f"https://graph.microsoft.com/{self._graph_api_version}"

    @property
    def base_url(self) -> Optional[str]:
        """Generic base URL property (OneDrive/SharePoint domain)"""
        return self._base_url
    
    @base_url.setter
    def base_url(self, value: str):
        """Set base URL"""
        self._base_url = value

    def set_file_infos(self, file_infos: List[Dict[str, Any]]) -> None:
        """
        Cache file metadata including download URLs for later use.
        This allows direct download without Graph API calls for sharing IDs.
        
        Args:
            file_infos: List of file info dicts with {id, name, mimeType, downloadUrl, size}
        """
        self._file_infos = {}
        for info in file_infos:
            file_id = info.get("id")
            if file_id:
                self._file_infos[file_id] = info
                if info.get("downloadUrl"):
                    logger.debug(f"Cached download URL for file {file_id}: {info.get('name')}")

    def get_cached_file_info(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get cached file info by ID."""
        return self._file_infos.get(file_id)

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

    async def _detect_base_url(self) -> Optional[str]:
        """Override base class method to detect OneDrive URL"""
        return await self._detect_onedrive_url()
    
    async def _detect_onedrive_url(self) -> Optional[str]:
        """Auto-detect OneDrive URL from Microsoft Graph API"""
        logger.info("_detect_onedrive_url: Starting OneDrive URL detection")
        try:
            if not self.oauth:
                logger.warning("_detect_onedrive_url: OAuth not initialized")
                return None
                
            access_token = self.oauth.get_access_token()
            logger.debug(f"_detect_onedrive_url: Got access token (length: {len(access_token) if access_token else 0})")
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            
            async with httpx.AsyncClient() as client:
                # Get user's default drive to extract OneDrive URL
                url = f"{self._graph_base_url}/me/drive"
                logger.info(f"_detect_onedrive_url: Calling Graph API: {url}")
                
                response = await client.get(url, headers=headers, timeout=30.0)
                logger.info(f"_detect_onedrive_url: Graph API response status: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    web_url = data.get("webUrl", "")
                    logger.info(f"_detect_onedrive_url: webUrl from response: {web_url}")
                    
                    # Extract the domain from the webUrl
                    # e.g., "https://onedrive.live.com/..." or "https://company-my.sharepoint.com/..."
                    if web_url:
                        parsed = urlparse(web_url)
                        onedrive_url = f"{parsed.scheme}://{parsed.netloc}"
                        logger.info(f"_detect_onedrive_url: Detected OneDrive URL: {onedrive_url}")
                        return onedrive_url
                    else:
                        logger.warning("_detect_onedrive_url: webUrl is empty in response")
                else:
                    logger.warning(f"_detect_onedrive_url: Failed to get drive info: {response.status_code}, response: {response.text[:500]}")
                    
        except Exception as e:
            logger.error(f"_detect_onedrive_url: Exception during detection: {e}")
            import traceback
            traceback.print_exc()
        
        return None

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

            # If file_ids or folder_ids are specified in config, use selective sync
            if self.cfg.file_ids or self.cfg.folder_ids:
                return await self._list_selected_files()

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

    async def _extract_onedrive_acl(self, file_id: str, file_metadata: Dict) -> DocumentACL:
        """
        Extract ACL from OneDrive item.

        Queries Microsoft Graph API permissions endpoint to get allowed users and groups.

        Args:
            file_id: OneDrive item ID
            file_metadata: File metadata dict

        Returns:
            DocumentACL instance with extracted permissions
        """
        try:
            # Get access token
            token_data = await self.oauth.get_access_token()
            access_token = token_data.get("access_token")

            if not access_token:
                logger.warning(f"No access token available for ACL extraction: {file_id}")
                return DocumentACL()

            # OneDrive permissions API endpoint
            permissions_url = f"{self._graph_base_url}/me/drive/items/{file_id}/permissions"

            # Fetch permissions
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    permissions_url,
                    headers={"Authorization": f"Bearer {access_token}"}
                )

            if response.status_code != 200:
                logger.warning(f"Failed to fetch permissions for {file_id}: {response.status_code}")
                return DocumentACL()

            permissions_data = response.json()

            allowed_users = []
            allowed_groups = []
            owner = None

            for perm in permissions_data.get("value", []):
                roles = perm.get("roles", [])  # ["read", "write", "owner"]

                # Granted to user
                if "grantedTo" in perm:
                    user_info = perm["grantedTo"].get("user", {})
                    email = user_info.get("email")
                    if email:
                        allowed_users.append(email)
                        if "owner" in roles:
                            owner = email

                # Granted to identities (can include users and groups)
                elif "grantedToIdentities" in perm:
                    for identity in perm["grantedToIdentities"]:
                        # User
                        if "user" in identity:
                            user_info = identity["user"]
                            email = user_info.get("email")
                            if email:
                                allowed_users.append(email)
                                if "owner" in roles:
                                    owner = email

                        # Group
                        elif "group" in identity:
                            group_info = identity["group"]
                            group_id = group_info.get("id")
                            group_display_name = group_info.get("displayName", group_id)
                            if group_id:
                                allowed_groups.append(group_display_name)

            return DocumentACL(
                owner=owner,
                allowed_users=allowed_users,
                allowed_groups=allowed_groups,
            )

        except Exception as e:
            logger.warning(f"Failed to extract ACL for OneDrive item {file_id}: {e}")
            return DocumentACL()

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        """Get file content and metadata."""
        try:
            if not await self.authenticate():
                raise RuntimeError("OneDrive authentication failed during file content retrieval")

            # First, check for cached file info with download URL
            # This is used for OneDrive sharing IDs that can't be resolved via Graph API
            cached_info = self.get_cached_file_info(file_id)
            if cached_info and cached_info.get("downloadUrl"):
                logger.info(f"Using cached download URL for file {file_id}")
                content = await self._download_file_from_url(cached_info["downloadUrl"])
                
                acl = DocumentACL(
                    owner="",
                    user_permissions={},
                    group_permissions={},
                )
                
                return ConnectorDocument(
                    id=file_id,
                    filename=cached_info.get("name", "Unknown"),
                    mimetype=cached_info.get("mimeType", "application/octet-stream"),
                    content=content,
                    source_url=cached_info.get("webUrl", ""),
                    acl=acl,
                    modified_time=datetime.now(),
                    created_time=datetime.now(),
                    metadata={
                        "onedrive_path": "",
                        "size": cached_info.get("size", 0),
                    },
                )

            # Fall back to Graph API for regular file IDs
            file_metadata = await self._get_file_metadata_by_id(file_id)
            if not file_metadata:
                # Last-resort: try shares endpoint download directly if this is a sharing ID
                if '!' in file_id and file_id.split('!', 1)[1].startswith('s'):
                    logger.info(f"No metadata for sharing ID {file_id}, attempting direct shares download")
                    token = self.oauth.get_access_token()
                    headers = {"Authorization": f"Bearer {token}"}
                    shares_content = await self._download_via_shares_endpoint(file_id, headers)
                    if shares_content is not None:
                        acl = DocumentACL(owner="", user_permissions={}, group_permissions={})
                        return ConnectorDocument(
                            id=file_id,
                            filename="Unknown",
                            mimetype="application/octet-stream",
                            content=shares_content,
                            source_url="",
                            acl=acl,
                            modified_time=datetime.now(),
                            created_time=datetime.now(),
                            metadata={"onedrive_path": "", "size": 0},
                        )
                raise ValueError(f"File not found: {file_id}")

            download_url = file_metadata.get("download_url")
            if download_url:
                content = await self._download_file_from_url(download_url)
            else:
                content = await self._download_file_content(file_id)

            # Extract ACL from OneDrive item
            acl = await self._extract_onedrive_acl(file_id, file_metadata)

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
        """Get file metadata by ID using Graph API.
        
        Handles multiple ID formats:
        - Standard item ID: uses /me/drive/items/{id}
        - Personal OneDrive format (driveId!itemId): uses /drives/{driveId}/items/{itemId}
        - Sharing IDs (with !s prefix): uses /shares endpoint
        """
        try:
            # Try different endpoints based on ID format
            item = await self._fetch_item_metadata(file_id)
            
            if not item:
                return None

            # Check if it's a folder
            if item.get("folder"):
                return {
                    "id": file_id,
                    "name": item.get("name", ""),
                    "isFolder": True,
                }

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
                    "isFolder": False,
                }

            return None

        except Exception as e:
            logger.error(f"Failed to get file metadata for {file_id}: {e}")
            return None

    async def _fetch_item_metadata(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Fetch item metadata, trying multiple endpoints for different ID formats."""
        import base64
        params = dict(self._default_params)
        
        # Check if ID contains '!' which indicates driveId!itemId format
        if '!' in file_id:
            parts = file_id.split('!', 1)
            if len(parts) == 2:
                drive_id = parts[0]
                item_id = parts[1]
                
                # Handle sharing IDs (item ID starts with 's')
                if item_id.startswith('s'):
                    logger.info(f"Detected sharing ID format for {file_id}")
                    
                    # Try multiple encoding approaches for the shares endpoint
                    share_encodings = [
                        # Approach 1: Encode the full ID with "u!" prefix
                        base64.urlsafe_b64encode(f"u!{file_id}".encode()).decode().rstrip('='),
                        # Approach 2: Encode just the share token with "s!" prefix
                        base64.urlsafe_b64encode(f"s!{item_id}".encode()).decode().rstrip('='),
                        # Approach 3: Encode the ID directly
                        base64.urlsafe_b64encode(file_id.encode()).decode().rstrip('='),
                        # Approach 4: Use the ID as-is (some APIs accept this)
                        f"u!{file_id}",
                    ]
                    
                    for i, encoded in enumerate(share_encodings):
                        try:
                            url = f"{self._graph_base_url}/shares/{encoded}/driveItem"
                            logger.debug(f"Trying shares endpoint approach {i+1}: {url}")
                            response = await self._make_graph_request(url, params=params)
                            if response.status_code == 200:
                                logger.info(f"Shares endpoint approach {i+1} succeeded")
                                return response.json()
                            else:
                                logger.debug(f"Shares approach {i+1} failed with status {response.status_code}")
                        except Exception as e:
                            logger.debug(f"Shares approach {i+1} failed: {e}")
                
                # Try: /drives/{driveId}/items/{itemId} with full item ID (including 's' prefix)
                logger.info(f"Trying drives endpoint: /drives/{drive_id}/items/{item_id}")
                try:
                    url = f"{self._graph_base_url}/drives/{drive_id}/items/{item_id}"
                    response = await self._make_graph_request(url, params=params)
                    if response.status_code == 200:
                        return response.json()
                except Exception as e:
                    logger.debug(f"Drives endpoint failed: {e}")
                
                # Try: /drives/{driveId}/items/{itemId} without 's' prefix
                if item_id.startswith('s'):
                    clean_item_id = item_id[1:]  # Remove 's' prefix
                    logger.info(f"Trying drives endpoint without 's' prefix: /drives/{drive_id}/items/{clean_item_id}")
                    try:
                        url = f"{self._graph_base_url}/drives/{drive_id}/items/{clean_item_id}"
                        response = await self._make_graph_request(url, params=params)
                        if response.status_code == 200:
                            return response.json()
                    except Exception as e:
                        logger.debug(f"Drives endpoint (no prefix) failed: {e}")
                
                # Try: /me/drive/items/{full_id} as fallback
                logger.info(f"Trying standard endpoint: /me/drive/items/{file_id}")
                try:
                    url = f"{self._graph_base_url}/me/drive/items/{file_id}"
                    response = await self._make_graph_request(url, params=params)
                    if response.status_code == 200:
                        return response.json()
                except Exception as e:
                    logger.debug(f"Standard endpoint failed: {e}")
        else:
            # Standard item ID without '!'
            url = f"{self._graph_base_url}/me/drive/items/{file_id}"
            response = await self._make_graph_request(url, params=params)
            if response.status_code == 200:
                return response.json()
        
        logger.error(f"All endpoints failed for file_id: {file_id}")
        return None

    async def _download_file_content(self, file_id: str) -> bytes:
        """Download file content by file ID using Graph API.
        
        Handles multiple ID formats like _get_file_metadata_by_id.
        """
        try:
            token = self.oauth.get_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            
            # Build URL based on ID format
            if '!' in file_id:
                parts = file_id.split('!', 1)
                if len(parts) == 2:
                    drive_id = parts[0]
                    item_id = parts[1]
                    
                    # If this looks like a sharing ID (starts with 's'), try shares endpoint first
                    if item_id.startswith('s'):
                        content = await self._download_via_shares_endpoint(file_id, headers)
                        if content is not None:
                            return content

                    # Try drives endpoint for driveId!itemId format (including the 's' prefix)
                    url = f"{self._graph_base_url}/drives/{drive_id}/items/{item_id}/content"
                    logger.info(f"Downloading via drives endpoint: {url}")
                else:
                    url = f"{self._graph_base_url}/me/drive/items/{file_id}/content"
            else:
                url = f"{self._graph_base_url}/me/drive/items/{file_id}/content"

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=60, follow_redirects=True)
                response.raise_for_status()
                return response.content

        except Exception as e:
            logger.error(f"Failed to download file content for {file_id}: {e}")
            raise

    async def _download_via_shares_endpoint(self, file_id: str, headers: Dict[str, str]) -> Optional[bytes]:
        """
        Attempt to download content using the Graph /shares endpoint for sharing IDs.
        """
        import base64

        share_encodings = [
            base64.urlsafe_b64encode(f"u!{file_id}".encode()).decode().rstrip('='),
            base64.urlsafe_b64encode(f"s!{file_id}".encode()).decode().rstrip('='),
            base64.urlsafe_b64encode(file_id.encode()).decode().rstrip('='),
            f"u!{file_id}",
        ]

        for i, encoded in enumerate(share_encodings):
            try:
                url = f"{self._graph_base_url}/shares/{encoded}/driveItem/content"
                logger.info(f"Attempting shares download (approach {i+1}): {url}")
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, headers=headers, timeout=60, follow_redirects=True)
                    if response.status_code == 200:
                        return response.content
                    else:
                        logger.debug(f"Shares download approach {i+1} failed with status {response.status_code}")
            except Exception as e:
                logger.debug(f"Shares download approach {i+1} failed: {e}")

        return None

    async def _download_file_from_url(self, download_url: str) -> bytes:
        """Download file content from direct download URL."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(download_url, timeout=60, follow_redirects=True)
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

    async def _list_selected_files(self) -> Dict[str, Any]:
        """List only selected files/folders (selective sync)."""
        files: List[Dict[str, Any]] = []
        
        # Process selected file IDs
        if self.cfg.file_ids:
            for file_id in self.cfg.file_ids:
                try:
                    file_meta = await self._get_file_metadata_by_id(file_id)
                    if file_meta and not file_meta.get('isFolder', False):
                        files.append(file_meta)
                    elif file_meta and file_meta.get('isFolder', False):
                        # If it's a folder, expand its contents
                        folder_files = await self._list_folder_contents(file_id)
                        files.extend(folder_files)
                except Exception as e:
                    logger.warning(f"Failed to get file {file_id}: {e}")
                    continue
        
        # Process selected folder IDs
        if self.cfg.folder_ids:
            for folder_id in self.cfg.folder_ids:
                try:
                    folder_files = await self._list_folder_contents(folder_id)
                    files.extend(folder_files)
                except Exception as e:
                    logger.warning(f"Failed to list folder {folder_id}: {e}")
                    continue
        
        return {"files": files, "next_page_token": None}
    
    async def _list_folder_contents(self, folder_id: str) -> List[Dict[str, Any]]:
        """List all files in a folder recursively."""
        files: List[Dict[str, Any]] = []
        
        try:
            url = f"{self._graph_base_url}/me/drive/items/{folder_id}/children"
            params = dict(self._default_params)
            
            response = await self._make_graph_request(url, params=params)
            data = response.json()
            
            items = data.get("value", [])
            for item in items:
                if item.get("file"):  # It's a file
                    file_meta = await self._get_file_metadata_by_id(item.get("id"))
                    if file_meta:
                        files.append(file_meta)
                elif item.get("folder"):  # It's a subfolder, recurse
                    subfolder_files = await self._list_folder_contents(item.get("id"))
                    files.extend(subfolder_files)
        except Exception as e:
            logger.error(f"Failed to list folder contents for {folder_id}: {e}")
        
        return files

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
