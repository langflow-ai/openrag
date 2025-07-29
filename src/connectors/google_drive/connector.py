import asyncio
import io
import os
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from ..base import BaseConnector, ConnectorDocument, DocumentACL
from .oauth import GoogleDriveOAuth


# Global worker service cache for process pools
_worker_drive_service = None

def get_worker_drive_service(client_id: str, token_file: str):
    """Get or create a Google Drive service instance for this worker process"""
    global _worker_drive_service
    if _worker_drive_service is None:
        print(f"🔧 Initializing Google Drive service in worker process (PID: {os.getpid()})")
        
        # Create OAuth instance and load credentials in worker
        from .oauth import GoogleDriveOAuth
        oauth = GoogleDriveOAuth(client_id=client_id, token_file=token_file)
        
        # Load credentials synchronously in worker
        import asyncio
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
def _sync_list_files_worker(client_id, token_file, query, page_token, page_size):
    """Worker function for listing files in process pool"""
    service = get_worker_drive_service(client_id, token_file)
    return service.files().list(
        q=query,
        pageSize=page_size,
        pageToken=page_token,
        fields="nextPageToken, files(id, name, mimeType, modifiedTime, createdTime, webViewLink, permissions, owners)"
    ).execute()


def _sync_get_metadata_worker(client_id, token_file, file_id):
    """Worker function for getting file metadata in process pool"""
    service = get_worker_drive_service(client_id, token_file)
    return service.files().get(
        fileId=file_id,
        fields="id, name, mimeType, modifiedTime, createdTime, webViewLink, permissions, owners, size"
    ).execute()


def _sync_download_worker(client_id, token_file, file_id, mime_type, file_size=None):
    """Worker function for downloading files in process pool"""
    import signal
    import time
    
    # File size limits (in bytes)
    MAX_REGULAR_FILE_SIZE = 100 * 1024 * 1024  # 100MB for regular files
    MAX_GOOGLE_WORKSPACE_SIZE = 50 * 1024 * 1024  # 50MB for Google Workspace docs (they can't be streamed)
    
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
        service = get_worker_drive_service(client_id, token_file)
        
        # For Google native formats, export as PDF
        if mime_type.startswith('application/vnd.google-apps.'):
            export_format = 'application/pdf'
            request = service.files().export_media(fileId=file_id, mimeType=export_format)
        else:
            # For regular files, download directly
            request = service.files().get_media(fileId=file_id)
        
        # Download file with chunked approach
        file_io = io.BytesIO()
        downloader = MediaIoBaseDownload(file_io, request, chunksize=1024*1024)  # 1MB chunks
        
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
        'application/vnd.google-apps.document',  # Google Docs -> PDF
        'application/vnd.google-apps.presentation',  # Google Slides -> PDF
        'application/vnd.google-apps.spreadsheet',  # Google Sheets -> PDF
    }
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.oauth = GoogleDriveOAuth(
            client_id=config.get('client_id'),
            token_file=config.get('token_file', 'gdrive_token.json')
        )
        self.service = None
        self.webhook_channel_id = None
        
    async def authenticate(self) -> bool:
        """Authenticate with Google Drive"""
        try:
            if await self.oauth.is_authenticated():
                self.service = self.oauth.get_service()
                self._authenticated = True
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
            return channel_id
            
        except HttpError as e:
            print(f"Failed to set up subscription: {e}")
            raise
    
    def _get_start_page_token(self) -> str:
        """Get the current page token for change notifications"""
        return self.service.changes().getStartPageToken().execute()['startPageToken']
    
    async def list_files(self, page_token: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        """List all supported files in Google Drive"""
        if not self._authenticated:
            raise ValueError("Not authenticated")
        
        # Build query for supported file types
        mimetype_query = " or ".join([f"mimeType='{mt}'" for mt in self.SUPPORTED_MIMETYPES])
        query = f"({mimetype_query}) and trashed=false"
        
        # Use provided limit or default to 100, max 1000 (Google Drive API limit)
        page_size = min(limit or 100, 1000)
        
        try:
            # Run the blocking Google API call in a thread pool to avoid blocking the event loop
            import asyncio
            loop = asyncio.get_event_loop()
            
            # Use the same process pool as docling processing
            from app import process_pool
            results = await loop.run_in_executor(
                process_pool, 
                _sync_list_files_worker, 
                self.oauth.client_id,
                self.oauth.token_file,
                query, 
                page_token,  # page_token should come before page_size
                page_size
            )
            
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
            import asyncio
            loop = asyncio.get_event_loop()
            
            # Use the same process pool as docling processing
            from app import process_pool
            file_metadata = await loop.run_in_executor(
                process_pool, 
                _sync_get_metadata_worker, 
                self.oauth.client_id,
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
        import asyncio
        loop = asyncio.get_event_loop()
        
        # Use the same process pool as docling processing
        from app import process_pool
        return await loop.run_in_executor(
            process_pool, 
            _sync_download_worker, 
            self.oauth.client_id,
            self.oauth.token_file,
            file_id, 
            mime_type,
            file_size
        )
    
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
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> List[str]:
        """Handle Google Drive webhook notification"""
        if not self._authenticated:
            raise ValueError("Not authenticated")
        
        # Google Drive sends change notifications
        # We need to query for actual changes
        try:
            page_token = payload.get('pageToken')
            if not page_token:
                # Get current page token and return empty list
                return []
            
            # Get list of changes
            changes = self.service.changes().list(
                pageToken=page_token,
                fields="changes(fileId, file(id, name, mimeType, trashed))"
            ).execute()
            
            affected_files = []
            for change in changes.get('changes', []):
                file_info = change.get('file', {})
                # Only include supported file types that aren't trashed
                if (file_info.get('mimeType') in self.SUPPORTED_MIMETYPES and 
                    not file_info.get('trashed', False)):
                    affected_files.append(change['fileId'])
            
            return affected_files
            
        except HttpError as e:
            print(f"Failed to handle webhook: {e}")
            return []
    
    async def cleanup_subscription(self, subscription_id: str) -> bool:
        """Clean up Google Drive subscription"""
        if not self._authenticated:
            return False
        
        try:
            self.service.channels().stop(
                body={
                    'id': subscription_id,
                    'resourceId': subscription_id  # This might need adjustment based on Google's response
                }
            ).execute()
            return True
        except HttpError as e:
            print(f"Failed to cleanup subscription: {e}")
            return False