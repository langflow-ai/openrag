import asyncio
import io
import os
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional, Set

from googleapiclient.discovery import build  # noqa: F401 (kept for symmetry with oauth)
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from ..base import BaseConnector, ConnectorDocument, DocumentACL
from .oauth import GoogleDriveOAuth


# Global worker service cache for process pools
_worker_drive_service = None


def get_worker_drive_service(client_id: str, client_secret: str, token_file: str):
    """Get or create a Google Drive service instance for this worker process"""
    global _worker_drive_service
    if _worker_drive_service is None:
        print(f"🔧 Initializing Google Drive service in worker process (PID: {os.getpid()})")

        # Create OAuth instance and load credentials in worker
        from .oauth import GoogleDriveOAuth as _GoogleDriveOAuth
        oauth = _GoogleDriveOAuth(client_id=client_id, client_secret=client_secret, token_file=token_file)

        # Load credentials synchronously in worker
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(oauth.load_credentials())
            _worker_drive_service = oauth.get_service()
            print(f"✅ Google Drive service ready in worker process (PID: {os.getpid()})")
        finally:
            loop.close()

    return _worker_drive_service


# Module-level functions for process pool execution (must be pickleable)
def _sync_list_files_worker(client_id, client_secret, token_file, query, page_token, page_size):
    """Worker function for listing files in process pool"""
    service = get_worker_drive_service(client_id, client_secret, token_file)
    return service.files().list(
        q=query,
        pageSize=page_size,
        pageToken=page_token,
        fields="nextPageToken, files(id, name, mimeType, modifiedTime, createdTime, webViewLink, permissions, owners)"
    ).execute()


def _sync_get_metadata_worker(client_id, client_secret, token_file, file_id):
    """Worker function for getting file metadata in process pool"""
    service = get_worker_drive_service(client_id, client_secret, token_file)
    return service.files().get(
        fileId=file_id,
        fields="id, name, mimeType, modifiedTime, createdTime, webViewLink, permissions, owners, size, trashed, parents"
    ).execute()


def _sync_download_worker(client_id, client_secret, token_file, file_id, mime_type, file_size=None):
    """Worker function for downloading files in process pool"""
    import signal
    import time

    # File size limits (in bytes)
    MAX_REGULAR_FILE_SIZE = 1000 * 1024 * 1024  # 1000MB for regular files
    MAX_GOOGLE_WORKSPACE_SIZE = 500 * 1024 * 1024  # 500MB for Google Workspace docs (they can't be streamed)

    # Check file size limits
    if file_size:
        if mime_type.startswith('application/vnd.google-apps.') and file_size > MAX_GOOGLE_WORKSPACE_SIZE:
            raise ValueError(f"Google Workspace file too large: {file_size} bytes (max {MAX_GOOGLE_WORKSPACE_SIZE})")
        elif not mime_type.startswith('application/vnd.google-apps.') and file_size > MAX_REGULAR_FILE_SIZE:
            raise ValueError(f"File too large: {file_size} bytes (max {MAX_REGULAR_FILE_SIZE})")

    # Dynamic timeout based on file size (minimum 60s, 10s per MB, max 300s)
    if file_size:
        file_size_mb = file_size / (1024 * 1024)
        timeout_seconds = min(300, max(60, int(file_size_mb * 10)))
    else:
        timeout_seconds = 60  # Default timeout if size unknown

    # Set a timeout for the entire download operation
    def timeout_handler(signum, frame):
        raise TimeoutError(f"File download timed out after {timeout_seconds} seconds")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_seconds)

    try:
        service = get_worker_drive_service(client_id, client_secret, token_file)

        # For Google native formats, export as PDF
        if mime_type.startswith('application/vnd.google-apps.'):
            export_format = 'application/pdf'
            request = service.files().export_media(fileId=file_id, mimeType=export_format)
        else:
            # For regular files, download directly
            request = service.files().get_media(fileId=file_id)

        # Download file with chunked approach
        file_io = io.BytesIO()
        downloader = MediaIoBaseDownload(file_io, request, chunksize=1024 * 1024)  # 1MB chunks

        done = False
        retry_count = 0
        max_retries = 2

        while not done and retry_count < max_retries:
            try:
                status, done = downloader.next_chunk()
                retry_count = 0  # Reset retry count on successful chunk
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    raise e
                time.sleep(1)  # Brief pause before retry

        return file_io.getvalue()

    finally:
        # Cancel the alarm
        signal.alarm(0)


class GoogleDriveConnector(BaseConnector):
    """Google Drive connector with OAuth and webhook support"""

    # OAuth environment variables
    CLIENT_ID_ENV_VAR = "GOOGLE_OAUTH_CLIENT_ID"
    CLIENT_SECRET_ENV_VAR = "GOOGLE_OAUTH_CLIENT_SECRET"

    # Connector metadata
    CONNECTOR_NAME = "Google Drive"
    CONNECTOR_DESCRIPTION = "Connect your Google Drive to automatically sync documents"
    CONNECTOR_ICON = "google-drive"

    # Supported file types that can be processed by docling
    SUPPORTED_MIMETYPES = {
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
        'application/msword',  # .doc
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',  # .pptx
        'application/vnd.ms-powerpoint',  # .ppt
        'text/plain',
        'text/html',
        'application/rtf',
        # Google Docs native formats - we'll export these
        'application/vnd.google-apps.document',       # Google Docs -> PDF
        'application/vnd.google-apps.presentation',   # Google Slides -> PDF
        'application/vnd.google-apps.spreadsheet',    # Google Sheets -> PDF
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.oauth = GoogleDriveOAuth(
            client_id=self.get_client_id(),
            client_secret=self.get_client_secret(),
            token_file=config.get('token_file', 'gdrive_token.json')
        )
        self.service = None
        # Load existing webhook channel ID from config if available
        self.webhook_channel_id = config.get('webhook_channel_id') or config.get('subscription_id')
        # Load existing webhook resource ID (Google Drive requires this to stop a channel)
        self.webhook_resource_id = config.get('resource_id')

        # ---- NEW: selection & filtering config ----
        # Explicit include lists
        self.selected_file_ids: Set[str] = set(config.get("file_ids") or config.get("selected_file_ids") or [])
        self.selected_folder_ids: Set[str] = set(config.get("folder_ids") or config.get("selected_folder_ids") or [])
        # Recursive traversal for folders (default True)
        self.recursive: bool = bool(config.get("recursive", True))
        # Optional MIME overrides
        self.include_mime_types: Set[str] = set(config.get("include_mime_types", []))
        self.exclude_mime_types: Set[str] = set(config.get("exclude_mime_types", []))
        # Cache of expanded folder IDs (when recursive)
        self._expanded_folder_ids: Optional[Set[str]] = None

    async def authenticate(self) -> bool:
        """Authenticate with Google Drive"""
        try:
            if await self.oauth.is_authenticated():
                self.service = self.oauth.get_service()
                self._authenticated = True
                # Pre-expand folder tree if needed
                if self.selected_folder_ids and self.recursive:
                    self._expanded_folder_ids = await self._expand_folders_recursive(self.selected_folder_ids)
                return True
            return False
        except Exception as e:
            print(f"Authentication failed: {e}")
            return False

    async def setup_subscription(self) -> str:
        """Set up Google Drive push notifications"""
        if not self._authenticated:
            raise ValueError("Not authenticated")

        # Generate unique channel ID
        channel_id = str(uuid.uuid4())

        # Set up push notification
        # Note: This requires a publicly accessible webhook endpoint
        webhook_url = self.config.get('webhook_url')
        if not webhook_url:
            raise ValueError("webhook_url required in config for subscriptions")

        try:
            body = {
                'id': channel_id,
                'type': 'web_hook',
                'address': webhook_url,
                'payload': True,
                'expiration': str(int((datetime.now().timestamp() + 86400) * 1000))  # 24 hours
            }

            result = self.service.changes().watch(
                pageToken=self._get_start_page_token(),
                body=body
            ).execute()

            self.webhook_channel_id = channel_id
            # Persist the resourceId returned by Google to allow proper cleanup
            try:
                self.webhook_resource_id = result.get('resourceId')
            except Exception:
                self.webhook_resource_id = None
            return channel_id

        except HttpError as e:
            print(f"Failed to set up subscription: {e}")
            raise

    def _get_start_page_token(self) -> str:
        """Get the current page token for change notifications"""
        return self.service.changes().getStartPageToken().execute()['startPageToken']

    async def list_files(self, page_token: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        """List supported files in Google Drive, scoped by selected folders/files if configured.

        Uses a thread pool (not the shared process pool) to avoid issues with
        Google API clients in forked processes and adds light retries for
        transient BrokenPipe/connection errors.
        """
        if not self._authenticated:
            raise ValueError("Not authenticated")

        # ---- compute MIME type filter (with optional overrides) ----
        effective_mimes = set(self.SUPPORTED_MIMETYPES)
        if self.include_mime_types:
            effective_mimes |= set(self.include_mime_types)
        if self.exclude_mime_types:
            effective_mimes -= set(self.exclude_mime_types)
        mimetype_query = " or ".join([f"mimeType='{mt}'" for mt in sorted(effective_mimes)])

        # ---- build parents scope if folders were selected ----
        parent_ids: Set[str] = set()
        if self.selected_folder_ids:
            if self.recursive:
                parent_ids = set(self._expanded_folder_ids or [])
            else:
                parent_ids = set(self.selected_folder_ids)
        parents_query = ""
        if parent_ids:
            parents_query = " and (" + " or ".join([f"'{fid}' in parents" for fid in sorted(parent_ids)]) + ")"

        # Final query
        query = f"({mimetype_query}) and trashed=false{parents_query}"

        # Use provided limit or default to 100, max 1000 (Google Drive API limit)
        page_size = min(limit or 100, 1000)

        # ---- fast-path explicit file IDs (ignores page_token/size intentionally) ----
        if self.selected_file_ids:
            files: List[Dict[str, Any]] = []
            loop = asyncio.get_event_loop()
            from utils.process_pool import process_pool

            async def fetch(fid: str):
                try:
                    meta = await loop.run_in_executor(
                        process_pool,
                        _sync_get_metadata_worker,
                        self.oauth.client_id,
                        self.oauth.client_secret,
                        self.oauth.token_file,
                        fid,
                    )
                    if meta.get("mimeType") in effective_mimes and not meta.get("trashed", False):
                        files.append({
                            'id': meta['id'],
                            'name': meta['name'],
                            'mimeType': meta['mimeType'],
                            'modifiedTime': meta['modifiedTime'],
                            'createdTime': meta['createdTime'],
                            'webViewLink': meta.get('webViewLink'),
                            'permissions': meta.get('permissions', []),
                            'owners': meta.get('owners', []),
                        })
                except Exception:
                    # Skip missing/forbidden IDs silently; caller can log if desired
                    pass

            await asyncio.gather(*[fetch(fid) for fid in sorted(self.selected_file_ids)])
            return {'files': files, 'nextPageToken': None}

        def _sync_list_files_inner():
            import time
            attempts = 0
            max_attempts = 3
            backoff = 1.0
            while True:
                try:
                    return self.service.files().list(
                        q=query,
                        pageSize=page_size,
                        pageToken=page_token,
                        fields="nextPageToken, files(id, name, mimeType, modifiedTime, createdTime, webViewLink, permissions, owners, parents, trashed)"
                    ).execute()
                except Exception as e:
                    attempts += 1
                    is_broken_pipe = isinstance(e, BrokenPipeError) or (
                        isinstance(e, OSError) and getattr(e, 'errno', None) == 32
                    )
                    if attempts < max_attempts and is_broken_pipe:
                        time.sleep(backoff)
                        backoff = min(4.0, backoff * 2)
                        continue
                    raise

        try:
            # Offload blocking HTTP call to default ThreadPoolExecutor
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, _sync_list_files_inner)

            files = []
            for file in results.get('files', []):
                files.append({
                    'id': file['id'],
                    'name': file['name'],
                    'mimeType': file['mimeType'],
                    'modifiedTime': file['modifiedTime'],
                    'createdTime': file['createdTime'],
                    'webViewLink': file['webViewLink'],
                    'permissions': file.get('permissions', []),
                    'owners': file.get('owners', [])
                })

            return {
                'files': files,
                'nextPageToken': results.get('nextPageToken')
            }

        except HttpError as e:
            print(f"Failed to list files: {e}")
            raise

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        """Get file content and metadata"""
        if not self._authenticated:
            raise ValueError("Not authenticated")

        try:
            # Get file metadata (run in thread pool to avoid blocking)
            loop = asyncio.get_event_loop()

            # Use the same process pool as docling processing
            from utils.process_pool import process_pool
            file_metadata = await loop.run_in_executor(
                process_pool,
                _sync_get_metadata_worker,
                self.oauth.client_id,
                self.oauth.client_secret,
                self.oauth.token_file,
                file_id
            )

            # Download file content (pass file size for timeout calculation)
            file_size = file_metadata.get('size')
            if file_size:
                file_size = int(file_size)  # Ensure it's an integer
            content = await self._download_file_content(file_id, file_metadata['mimeType'], file_size)

            # Extract ACL information
            acl = self._extract_acl(file_metadata)

            return ConnectorDocument(
                id=file_id,
                filename=file_metadata['name'],
                mimetype=file_metadata['mimeType'],
                content=content,
                source_url=file_metadata['webViewLink'],
                acl=acl,
                modified_time=datetime.fromisoformat(file_metadata['modifiedTime'].replace('Z', '+00:00')).replace(tzinfo=None),
                created_time=datetime.fromisoformat(file_metadata['createdTime'].replace('Z', '+00:00')).replace(tzinfo=None),
                metadata={
                    'size': file_metadata.get('size'),
                    'owners': file_metadata.get('owners', [])
                }
            )

        except HttpError as e:
            print(f"Failed to get file content: {e}")
            raise

    async def _download_file_content(self, file_id: str, mime_type: str, file_size: int = None) -> bytes:
        """Download file content, converting Google Docs formats if needed"""

        # Download file (run in process pool to avoid blocking)
        loop = asyncio.get_event_loop()

        # Use the same process pool as docling processing
        from utils.process_pool import process_pool
        return await loop.run_in_executor(
            process_pool,
            _sync_download_worker,
            self.oauth.client_id,
            self.oauth.client_secret,
            self.oauth.token_file,
            file_id,
            mime_type,
            file_size
        )

    # ---- helper to expand folder IDs recursively ----
    async def _expand_folders_recursive(self, root_folder_ids: Set[str]) -> Set[str]:
        """Return set of folder IDs including all descendants of root_folder_ids."""
        loop = asyncio.get_event_loop()
        FOLDER_MIME = "application/vnd.google-apps.folder"

        def _list_children(parents: Set[str]) -> List[Dict[str, Any]]:
            # Query: all folders whose parents include any in 'parents'
            # Chunk 'parents' to avoid overly long queries
            all_found: List[Dict[str, Any]] = []
            parent_list = list(parents)
            CHUNK = 20
            for i in range(0, len(parent_list), CHUNK):
                chunk = parent_list[i:i + CHUNK]
                parents_q = " or ".join([f"'{pid}' in parents" for pid in chunk])
                q = f"mimeType='{FOLDER_MIME}' and trashed=false and ({parents_q})"
                page_token = None
                while True:
                    resp = self.service.files().list(
                        q=q,
                        pageSize=1000,
                        pageToken=page_token,
                        fields="nextPageToken, files(id, parents)"
                    ).execute()
                    all_found.extend(resp.get("files", []))
                    page_token = resp.get("nextPageToken")
                    if not page_token:
                        break
            return all_found

        # BFS
        visited: Set[str] = set(root_folder_ids)
        frontier: Set[str] = set(root_folder_ids)
        while frontier:
            children = await loop.run_in_executor(None, _list_children, frontier)
            next_frontier: Set[str] = set()
            for f in children:
                fid = f.get("id")
                if fid and fid not in visited:
                    visited.add(fid)
                    next_frontier.add(fid)
            frontier = next_frontier
        return visited

    def _extract_acl(self, file_metadata: Dict[str, Any]) -> DocumentACL:
        """Extract ACL information from file metadata"""
        user_permissions = {}
        group_permissions = {}

        owner = None
        if file_metadata.get('owners'):
            owner = file_metadata['owners'][0].get('emailAddress')

        # Process permissions
        for perm in file_metadata.get('permissions', []):
            email = perm.get('emailAddress')
            role = perm.get('role', 'reader')
            perm_type = perm.get('type')

            if perm_type == 'user' and email:
                user_permissions[email] = role
            elif perm_type == 'group' and email:
                group_permissions[email] = role
            elif perm_type == 'domain':
                # Domain-wide permissions - could be treated as a group
                domain = perm.get('domain', 'unknown-domain')
                group_permissions[f"domain:{domain}"] = role

        return DocumentACL(
            owner=owner,
            user_permissions=user_permissions,
            group_permissions=group_permissions
        )

    def extract_webhook_channel_id(self, payload: Dict[str, Any], headers: Dict[str, str]) -> Optional[str]:
        """Extract Google Drive channel ID from webhook headers"""
        return headers.get('x-goog-channel-id')

    def extract_webhook_resource_id(self, headers: Dict[str, str]) -> Optional[str]:
        """Extract Google Drive resource ID from webhook headers"""
        return headers.get('x-goog-resource-id')

    async def handle_webhook(self, payload: Dict[str, Any]) -> List[str]:
        """Handle Google Drive webhook notification"""
        if not self._authenticated:
            raise ValueError("Not authenticated")

        # Google Drive sends headers with the important info
        headers = payload.get('_headers', {})

        # Extract Google Drive specific headers
        channel_id = headers.get('x-goog-channel-id')
        resource_state = headers.get('x-goog-resource-state')

        if not channel_id:
            print("[WEBHOOK] No channel ID found in Google Drive webhook")
            return []

        # Check if this webhook belongs to this connection
        if self.webhook_channel_id != channel_id:
            print(f"[WEBHOOK] Channel ID mismatch: expected {self.webhook_channel_id}, got {channel_id}")
            return []

        # Only process certain states (ignore 'sync' which is just a ping)
        if resource_state not in ['exists', 'not_exists', 'change']:
            print(f"[WEBHOOK] Ignoring resource state: {resource_state}")
            return []

        try:
            # Extract page token from the resource URI if available
            page_token = None
            headers = payload.get('_headers', {})
            resource_uri = headers.get('x-goog-resource-uri')

            if resource_uri and 'pageToken=' in resource_uri:
                # Extract page token from URI like:
                # https://www.googleapis.com/drive/v3/changes?alt=json&pageToken=4337807
                import urllib.parse
                parsed = urllib.parse.urlparse(resource_uri)
                query_params = urllib.parse.parse_qs(parsed.query)
                page_token = query_params.get('pageToken', [None])[0]

            if not page_token:
                print("[WEBHOOK] No page token found, cannot identify specific changes")
                return []

            print(f"[WEBHOOK] Getting changes since page token: {page_token}")

            # Get list of changes since the page token
            changes = self.service.changes().list(
                pageToken=page_token,
                fields="changes(fileId, file(id, name, mimeType, trashed, parents))"
            ).execute()

            # Recompute effective mimes (same as list_files)
            effective_mimes = set(self.SUPPORTED_MIMETYPES)
            if self.include_mime_types:
                effective_mimes |= set(self.include_mime_types)
            if self.exclude_mime_types:
                effective_mimes -= set(self.exclude_mime_types)

            affected_files = []
            for change in changes.get('changes', []):
                file_info = change.get('file', {}) or {}
                file_id = change.get('fileId')

                if not file_id:
                    continue

                # Only include supported file types that aren't trashed
                mime_type = file_info.get('mimeType', '')
                is_trashed = file_info.get('trashed', False)

                # ---- scope filtering for webhook ----
                in_scope = True
                # file-based inclusion
                if self.selected_file_ids and file_id not in self.selected_file_ids:
                    in_scope = False
                # folder-based inclusion
                if in_scope and self.selected_folder_ids:
                    allowed_parents = self._expanded_folder_ids if self.recursive else self.selected_folder_ids
                    file_parents = set((file_info.get('parents') or []))
                    if not (file_parents & set(allowed_parents or [])):
                        in_scope = False

                if not is_trashed and mime_type in effective_mimes and in_scope:
                    print(f"[WEBHOOK] File changed: {file_info.get('name', 'Unknown')} ({file_id})")
                    affected_files.append(file_id)
                elif is_trashed:
                    print(f"[WEBHOOK] File deleted/trashed: {file_info.get('name', 'Unknown')} ({file_id})")
                    # TODO: Handle file deletion (remove from index)
                else:
                    print(f"[WEBHOOK] Ignoring unsupported or out-of-scope file: mime={mime_type} id={file_id}")

            print(f"[WEBHOOK] Found {len(affected_files)} affected supported files")
            return affected_files

        except HttpError as e:
            print(f"Failed to handle webhook: {e}")
            return []

    async def cleanup_subscription(self, subscription_id: str) -> bool:
        """Clean up Google Drive subscription for this connection.

        Uses the stored resource_id captured during subscription setup.
        """
        if not self._authenticated:
            return False

        try:
            # Google Channels API requires both 'id' (channel) and 'resourceId'
            if not self.webhook_resource_id:
                raise ValueError("Missing resource_id for cleanup; ensure subscription state is persisted")
            body = {'id': subscription_id, 'resourceId': self.webhook_resource_id}

            self.service.channels().stop(body=body).execute()
            return True
        except HttpError as e:
            print(f"Failed to cleanup subscription: {e}")
            return False
