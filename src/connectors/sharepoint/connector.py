import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
from datetime import datetime
import httpx

from ..base import BaseConnector, ConnectorDocument, DocumentACL
from .oauth import SharePointOAuth

logger = logging.getLogger(__name__)


class SharePointConnector(BaseConnector):
    """SharePoint connector using MSAL-based OAuth for authentication"""

    # Required BaseConnector class attributes
    CLIENT_ID_ENV_VAR = "MICROSOFT_GRAPH_OAUTH_CLIENT_ID"
    CLIENT_SECRET_ENV_VAR = "MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET"  # pragma: allowlist secret
    
    # Connector metadata
    CONNECTOR_NAME = "SharePoint"
    CONNECTOR_DESCRIPTION = "Add knowledge from SharePoint"
    CONNECTOR_ICON = "sharepoint"
        
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        logger.debug(f"SharePoint connector __init__ called with config type: {type(config)}")
        logger.debug(f"SharePoint connector __init__ config value: {config}")
        
        # Ensure we always pass a valid config to the base class
        if config is None:
            logger.debug("Config was None, using empty dict")
            config = {}
        
        try:
            logger.debug("Calling super().__init__")
            super().__init__(config)  # Now safe to call with empty dict instead of None
            logger.debug("super().__init__ completed successfully")
        except Exception as e:
            logger.error(f"super().__init__ failed: {e}")
            raise
        
        # Initialize with defaults that allow the connector to be listed
        self.client_id = None
        self.client_secret = None
        self.tenant_id = config.get("tenant_id", "common")
        # base_url is the generic field name, sharepoint_url is kept for backward compatibility
        self.sharepoint_url = config.get("base_url") or config.get("sharepoint_url")
        logger.debug(f"SharePoint connector initialized with sharepoint_url from config: {self.sharepoint_url}")
        self.redirect_uri = config.get("redirect_uri", "http://localhost")
        
        # Try to get credentials, but don't fail if they're missing
        try:
            logger.debug("Attempting to get client_id")
            self.client_id = self.get_client_id()
            logger.debug(f"Got client_id: {self.client_id is not None}")
        except Exception as e:
            logger.debug(f"Failed to get client_id: {e}")
            pass  # Credentials not available, that's OK for listing
        
        try:
            logger.debug("Attempting to get client_secret")
            self.client_secret = self.get_client_secret()
            logger.debug(f"Got client_secret: {self.client_secret is not None}")
        except Exception as e:
            logger.debug(f"Failed to get client_secret: {e}")
            pass  # Credentials not available, that's OK for listing

        # Token file setup - use data/ directory for persistence
        token_file = config.get("token_file") or "data/sharepoint_token.json"
        Path(token_file).parent.mkdir(parents=True, exist_ok=True)

        # Only initialize OAuth if we have credentials
        if self.client_id and self.client_secret:
            connection_id = config.get("connection_id", "default")

            # Use token_file from config if provided, otherwise generate one
            if config.get("token_file"):
                oauth_token_file = config["token_file"]
            else:
                oauth_token_file = f"data/sharepoint_token_{connection_id}.json"
            
            authority = f"https://login.microsoftonline.com/{self.tenant_id}" if self.tenant_id != "common" else "https://login.microsoftonline.com/common"
            
            self.oauth = SharePointOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                token_file=oauth_token_file,
                authority=authority
            )
        else:
            self.oauth = None
        
        # Track subscription ID for webhooks
        self._subscription_id: Optional[str] = None
        
        # Add Graph API defaults similar to Google Drive flags
        self._graph_api_version = "v1.0"
        self._default_params = {
            "$select": "id,name,size,lastModifiedDateTime,createdDateTime,webUrl,file,folder,@microsoft.graph.downloadUrl"
        }
        
        # Selective sync support (similar to Google Drive and OneDrive)
        self.cfg = type('SharePointConfig', (), {
            'file_ids': config.get('file_ids') or config.get('selected_files') or config.get('selected_file_ids'),
            'folder_ids': config.get('folder_ids') or config.get('selected_folders') or config.get('selected_folder_ids'),
        })()
        
        # Cache for file metadata including download URLs
        # This allows direct download without Graph API for sharing IDs
        self._file_infos: Dict[str, Dict[str, Any]] = {}
    
    @property
    def _graph_base_url(self) -> str:
        """Base URL for Microsoft Graph API calls"""
        return f"https://graph.microsoft.com/{self._graph_api_version}"
    
    @property
    def base_url(self) -> Optional[str]:
        """Generic base URL property (returns sharepoint_url for SharePoint connector)"""
        return self.sharepoint_url
    
    @base_url.setter
    def base_url(self, value: str):
        """Set base URL (updates sharepoint_url internally)"""
        self.sharepoint_url = value

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
        """
        Emit a ConnectorDocument instance.
        """
        logger.debug(f"Emitting SharePoint document: {doc.id} ({doc.filename})")
    
    async def authenticate(self) -> bool:
        """Test authentication - BaseConnector interface"""
        logger.debug(f"SharePoint authenticate() called, oauth is None: {self.oauth is None}")
        try:
            if not self.oauth:
                logger.debug("SharePoint authentication failed: OAuth not initialized")
                self._authenticated = False
                return False
                
            logger.debug("Loading SharePoint credentials...")
            # Try to load existing credentials first
            load_result = await self.oauth.load_credentials()
            logger.debug(f"Load credentials result: {load_result}")
            
            logger.debug("Checking SharePoint authentication status...")
            authenticated = await self.oauth.is_authenticated()
            logger.debug(f"SharePoint is_authenticated result: {authenticated}")
            
            self._authenticated = authenticated
            return authenticated
        except Exception as e:
            logger.error(f"SharePoint authentication failed: {e}")
            import traceback
            traceback.print_exc()
            self._authenticated = False
            return False
    
    def get_auth_url(self) -> str:
        """Get OAuth authorization URL"""
        if not self.oauth:
            raise RuntimeError("SharePoint OAuth not initialized - missing credentials")
        return self.oauth.create_authorization_url(self.redirect_uri)
    
    async def handle_oauth_callback(self, auth_code: str) -> Dict[str, Any]:
        """Handle OAuth callback"""
        if not self.oauth:
            raise RuntimeError("SharePoint OAuth not initialized - missing credentials")
        try:
            success = await self.oauth.handle_authorization_callback(auth_code, self.redirect_uri)
            if success:
                self._authenticated = True
                
                # Auto-detect base URL from user's drive
                detected_url = await self._detect_base_url()
                if detected_url:
                    self.base_url = detected_url
                    logger.info(f"Auto-detected base URL: {detected_url}")
                
                return {"status": "success", "base_url": self.base_url}
            else:
                raise ValueError("OAuth callback failed")
        except Exception as e:
            logger.error(f"OAuth callback failed: {e}")
            raise
    
    async def _detect_base_url(self) -> Optional[str]:
        """Override base class method to detect SharePoint URL"""
        return await self._detect_sharepoint_url()
    
    async def _detect_sharepoint_url(self) -> Optional[str]:
        """Auto-detect SharePoint URL from Microsoft Graph API"""
        logger.info("_detect_sharepoint_url: Starting SharePoint URL detection")
        try:
            if not self.oauth:
                logger.warning("_detect_sharepoint_url: OAuth not initialized")
                return None
                
            access_token = self.oauth.get_access_token()
            logger.debug(f"_detect_sharepoint_url: Got access token (length: {len(access_token) if access_token else 0})")
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            
            async with httpx.AsyncClient() as client:
                # Get user's default drive to extract SharePoint URL
                url = f"{self._graph_base_url}/me/drive"
                logger.info(f"_detect_sharepoint_url: Calling Graph API: {url}")
                
                response = await client.get(url, headers=headers, timeout=30.0)
                logger.info(f"_detect_sharepoint_url: Graph API response status: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    web_url = data.get("webUrl", "")
                    logger.info(f"_detect_sharepoint_url: webUrl from response: {web_url}")
                    
                    # Extract the SharePoint domain from the webUrl

                    if web_url:
                        parsed = urlparse(web_url)
                        sharepoint_url = f"{parsed.scheme}://{parsed.netloc}"
                        logger.info(f"_detect_sharepoint_url: Detected SharePoint URL: {sharepoint_url}")
                        return sharepoint_url
                    else:
                        logger.warning("_detect_sharepoint_url: webUrl is empty in response")
                else:
                    logger.warning(f"_detect_sharepoint_url: Failed to get drive info: {response.status_code}, response: {response.text[:500]}")
                    
        except Exception as e:
            logger.error(f"_detect_sharepoint_url: Exception during detection: {e}")
            import traceback
            traceback.print_exc()
        
        return None
    
    def sync_once(self) -> None:
        """
        Perform a one-shot sync of SharePoint files and emit documents.
        This method mirrors the Google Drive connector's sync_once functionality.
        """
        import asyncio
        
        async def _async_sync():
            try:
                # Get list of files
                file_list = await self.list_files(max_files=1000)  # Adjust as needed
                files = file_list.get("files", [])
                
                for file_info in files:
                    try:
                        file_id = file_info.get("id")
                        if not file_id:
                            continue
                        
                        # Get full document content
                        doc = await self.get_file_content(file_id)
                        self.emit(doc)
                        
                    except Exception as e:
                        logger.error(f"Failed to sync SharePoint file {file_info.get('name', 'unknown')}: {e}")
                        continue
                        
            except Exception as e:
                logger.error(f"SharePoint sync_once failed: {e}")
                raise
        
        # Run the async sync
        if hasattr(asyncio, 'run'):
            asyncio.run(_async_sync())
        else:
            # Python < 3.7 compatibility
            loop = asyncio.get_event_loop()
            loop.run_until_complete(_async_sync())
    
    async def setup_subscription(self) -> str:
        """Set up real-time subscription for file changes - BaseConnector interface"""
        webhook_url = self.config.get('webhook_url')
        if not webhook_url:
            logger.warning("No webhook URL configured, skipping SharePoint subscription setup")
            return "no-webhook-configured"
        
        try:
            # Ensure we're authenticated
            if not await self.authenticate():
                raise RuntimeError("SharePoint authentication failed during subscription setup")
            
            token = self.oauth.get_access_token()
            
            # Microsoft Graph subscription for SharePoint site
            site_info = self._parse_sharepoint_url()
            if site_info:
                resource = f"sites/{site_info['host_name']}:/sites/{site_info['site_name']}:/drive/root"
            else:
                resource = "/me/drive/root"
            
            subscription_data = {
                "changeType": "created,updated,deleted",
                "notificationUrl": f"{webhook_url}/webhook/sharepoint",
                "resource": resource,
                "expirationDateTime": self._get_subscription_expiry(),
                "clientState": f"sharepoint_{self.tenant_id}"
            }
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            url = f"{self._graph_base_url}/subscriptions"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=subscription_data, headers=headers, timeout=30)
                response.raise_for_status()
                
                result = response.json()
                subscription_id = result.get("id")
                
                if subscription_id:
                    self._subscription_id = subscription_id
                    logger.info(f"SharePoint subscription created: {subscription_id}")
                    return subscription_id
                else:
                    raise ValueError("No subscription ID returned from Microsoft Graph")
                
        except Exception as e:
            logger.error(f"Failed to setup SharePoint subscription: {e}")
            raise
    
    def _get_subscription_expiry(self) -> str:
        """Get subscription expiry time (max 3 days for Graph API)"""
        from datetime import datetime, timedelta
        expiry = datetime.utcnow() + timedelta(days=3)  # 3 days max for Graph
        return expiry.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    
    def _parse_sharepoint_url(self) -> Optional[Dict[str, str]]:
        """Parse SharePoint URL to extract site information for Graph API"""
        if not self.sharepoint_url:
            return None
        
        try:
            parsed = urlparse(self.sharepoint_url)
            # Extract hostname and site name from URL like: https://contoso.sharepoint.com/sites/teamsite
            host_name = parsed.netloc
            path_parts = parsed.path.strip('/').split('/')
            
            if len(path_parts) >= 2 and path_parts[0] == 'sites':
                site_name = path_parts[1]
                return {
                    "host_name": host_name,
                    "site_name": site_name
                }
        except Exception as e:
            logger.warning(f"Could not parse SharePoint URL {self.sharepoint_url}: {e}")
        
        return None
    
    async def list_files(
        self,
        page_token: Optional[str] = None,
        max_files: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """List all files using Microsoft Graph API - BaseConnector interface"""
        try:
            # Ensure authentication
            if not await self.authenticate():
                raise RuntimeError("SharePoint authentication failed during file listing")
            
            # If file_ids or folder_ids are specified in config, use selective sync
            if self.cfg.file_ids or self.cfg.folder_ids:
                return await self._list_selected_files()
            
            files = []
            max_files_value = max_files if max_files is not None else 100
            
            # Build Graph API URL for the site or fallback to user's OneDrive
            site_info = self._parse_sharepoint_url()
            if site_info:
                base_url = f"{self._graph_base_url}/sites/{site_info['host_name']}:/sites/{site_info['site_name']}:/drive/root/children"
            else:
                base_url = f"{self._graph_base_url}/me/drive/root/children"
            
            params = dict(self._default_params)
            params["$top"] = str(max_files_value)
            
            if page_token:
                params["$skiptoken"] = page_token
            
            response = await self._make_graph_request(base_url, params=params)
            data = response.json()
            
            items = data.get("value", [])
            for item in items:
                # Only include files, not folders
                if item.get("file"):
                    files.append({
                        "id": item.get("id", ""),
                        "name": item.get("name", ""),
                        "path": f"/drive/items/{item.get('id')}",
                        "size": int(item.get("size", 0)),
                        "modified": item.get("lastModifiedDateTime"),
                        "created": item.get("createdDateTime"),
                        "mime_type": item.get("file", {}).get("mimeType", self._get_mime_type(item.get("name", ""))),
                        "url": item.get("webUrl", ""),
                        "download_url": item.get("@microsoft.graph.downloadUrl")
                    })

            # Check for next page
            next_page_token = None
            next_link = data.get("@odata.nextLink")
            if next_link:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(next_link)
                query_params = parse_qs(parsed.query)
                if "$skiptoken" in query_params:
                    next_page_token = query_params["$skiptoken"][0]

            return {
                "files": files,
                "next_page_token": next_page_token
            }

        except Exception as e:
            logger.error(f"Failed to list SharePoint files: {e}")
            return {"files": [], "next_page_token": None}  # Return empty result instead of raising
    
    async def _extract_sharepoint_acl(self, file_id: str, file_metadata: Dict) -> DocumentACL:
        """
        Extract ACL from SharePoint item.

        Queries Microsoft Graph API permissions endpoint to get allowed users and groups.

        Args:
            file_id: SharePoint item ID
            file_metadata: File metadata dict

        Returns:
            DocumentACL instance with extracted permissions
        """
        try:
            # Get access token - use same approach as _make_graph_request
            access_token = self.oauth.get_access_token()

            if not access_token:
                logger.warning(f"No access token available for ACL extraction: {file_id}")
                return DocumentACL()

            # Determine the correct path for permissions API call
            # Use the same URL pattern as _get_file_metadata_by_id and list_files
            site_info = self._parse_sharepoint_url()
            if site_info:
                permissions_url = f"{self._graph_base_url}/sites/{site_info['host_name']}:/sites/{site_info['site_name']}:/drive/items/{file_id}/permissions"
            else:
                # Fallback to user drive
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

                # Granted to user (grantedTo or grantedToV2)
                granted_to = perm.get("grantedToV2") or perm.get("grantedTo")
                if granted_to:
                    user_info = granted_to.get("user", {})
                    email = user_info.get("email")
                    display_name = user_info.get("displayName")
                    user_identifier = email or display_name
                    if user_identifier:
                        allowed_users.append(user_identifier)
                        if "owner" in roles:
                            owner = user_identifier

                # Granted to identities (can include users and groups)
                if "grantedToIdentitiesV2" in perm or "grantedToIdentities" in perm:
                    identities = perm.get("grantedToIdentitiesV2") or perm.get("grantedToIdentities") or []
                    for identity in identities:
                        # User
                        if "user" in identity:
                            user_info = identity["user"]
                            email = user_info.get("email")
                            display_name = user_info.get("displayName")
                            user_identifier = email or display_name
                            if user_identifier:
                                allowed_users.append(user_identifier)
                                if "owner" in roles:
                                    owner = user_identifier

                        # Group
                        if "group" in identity:
                            group_info = identity["group"]
                            group_id = group_info.get("id")
                            group_display_name = group_info.get("displayName", group_id)
                            if group_id or group_display_name:
                                allowed_groups.append(group_display_name or group_id)

            return DocumentACL(
                owner=owner,
                allowed_users=allowed_users,
                allowed_groups=allowed_groups,
            )

        except Exception as e:
            logger.warning(f"Failed to extract ACL for SharePoint item {file_id}: {e}")
            return DocumentACL()

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        """Get file content and metadata - BaseConnector interface"""
        try:
            # Ensure authentication
            if not await self.authenticate():
                raise RuntimeError("SharePoint authentication failed during file content retrieval")
            
            # First, check for cached file info with download URL
            # This is used for SharePoint sharing IDs that can't be resolved via Graph API
            cached_info = self.get_cached_file_info(file_id)
            if cached_info and cached_info.get("downloadUrl"):
                logger.info(f"Using cached download URL for file {file_id}")
                content = await self._download_file_from_url(cached_info["downloadUrl"])
                
                # Extract ACL even for cached files
                acl = await self._extract_sharepoint_acl(file_id, cached_info)
                
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
                        "sharepoint_path": "",
                        "sharepoint_url": self.sharepoint_url,
                        "size": cached_info.get("size", 0),
                    },
                )
            
            # Fall back to Graph API for regular file IDs
            file_metadata = await self._get_file_metadata_by_id(file_id)
            
            if not file_metadata:
                raise ValueError(f"File not found: {file_id}")
            
            # Download file content
            download_url = file_metadata.get("download_url")
            if download_url:
                content = await self._download_file_from_url(download_url)
            else:
                content = await self._download_file_content(file_id)
            
            # Extract ACL from SharePoint item
            acl = await self._extract_sharepoint_acl(file_id, file_metadata)
            
            # Parse dates
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
                    "sharepoint_path": file_metadata.get("path", ""),
                    "sharepoint_url": self.sharepoint_url,
                    "size": file_metadata.get("size", 0)
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to get SharePoint file content {file_id}: {e}")
            raise
    
    async def _get_file_metadata_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file metadata by ID using Graph API"""
        try:
            # Try site-specific path first, then fallback to user drive
            site_info = self._parse_sharepoint_url()
            if site_info:
                url = f"{self._graph_base_url}/sites/{site_info['host_name']}:/sites/{site_info['site_name']}:/drive/items/{file_id}"
            else:
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
                    "download_url": item.get("@microsoft.graph.downloadUrl")
                }
            
            # Check if it's a folder
            if item.get("folder"):
                return {
                    "id": file_id,
                    "name": item.get("name", ""),
                    "isFolder": True,
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get file metadata for {file_id}: {e}")
            return None
    
    async def _download_file_content(self, file_id: str) -> bytes:
        """Download file content by file ID using Graph API"""
        try:
            site_info = self._parse_sharepoint_url()
            if site_info:
                url = f"{self._graph_base_url}/sites/{site_info['host_name']}:/sites/{site_info['site_name']}:/drive/items/{file_id}/content"
            else:
                url = f"{self._graph_base_url}/me/drive/items/{file_id}/content"
            
            token = self.oauth.get_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=60, follow_redirects=True)
                response.raise_for_status()
                return response.content
            
        except Exception as e:
            logger.error(f"Failed to download file content for {file_id}: {e}")
            raise
    
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
            site_info = self._parse_sharepoint_url()
            if site_info:
                url = f"{self._graph_base_url}/sites/{site_info['host_name']}:/sites/{site_info['site_name']}:/drive/items/{folder_id}/children"
            else:
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
    
    async def _download_file_from_url(self, download_url: str) -> bytes:
        """Download file content from direct download URL"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(download_url, timeout=60, follow_redirects=True)
                response.raise_for_status()
                return response.content
        except Exception as e:
            logger.error(f"Failed to download from URL {download_url}: {e}")
            raise
    
    def _parse_graph_date(self, date_str: Optional[str]) -> datetime:
        """Parse Microsoft Graph date string to datetime"""
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
        """Make authenticated API request to Microsoft Graph"""
        token = self.oauth.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
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
        """Get MIME type based on file extension"""
        import mimetypes
        mime_type, _ = mimetypes.guess_type(filename)
        return mime_type or "application/octet-stream"
    
    # Webhook methods - BaseConnector interface
    def handle_webhook_validation(self, request_method: str, headers: Dict[str, str], 
                                 query_params: Dict[str, str]) -> Optional[str]:
        """Handle webhook validation (Graph API specific)"""
        if request_method == "POST" and "validationToken" in query_params:
            return query_params["validationToken"]
        return None
    
    def extract_webhook_channel_id(self, payload: Dict[str, Any], 
                                  headers: Dict[str, str]) -> Optional[str]:
        """Extract channel/subscription ID from webhook payload"""
        notifications = payload.get("value", [])
        if notifications:
            return notifications[0].get("subscriptionId")
        return None
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> List[str]:
        """Handle webhook notification and return affected file IDs"""
        affected_files = []
        
        # Process Microsoft Graph webhook payload
        notifications = payload.get("value", [])
        for notification in notifications:
            resource = notification.get("resource")
            if resource and "/drive/items/" in resource:
                file_id = resource.split("/drive/items/")[-1]
                affected_files.append(file_id)
        
        return affected_files
    
    async def cleanup_subscription(self, subscription_id: str) -> bool:
        """Clean up subscription - BaseConnector interface"""
        if subscription_id == "no-webhook-configured":
            logger.info("No subscription to cleanup (webhook was not configured)")
            return True
            
        try:
            # Ensure authentication
            if not await self.authenticate():
                logger.error("SharePoint authentication failed during subscription cleanup")
                return False
            
            token = self.oauth.get_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            
            url = f"{self._graph_base_url}/subscriptions/{subscription_id}"
            
            async with httpx.AsyncClient() as client:
                response = await client.delete(url, headers=headers, timeout=30)
                
                if response.status_code in [200, 204, 404]:
                    logger.info(f"SharePoint subscription {subscription_id} cleaned up successfully")
                    return True
                else:
                    logger.warning(f"Unexpected response cleaning up subscription: {response.status_code}")
                    return False
                
        except Exception as e:
            logger.error(f"Failed to cleanup SharePoint subscription {subscription_id}: {e}")
            return False
