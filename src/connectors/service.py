import asyncio
import tempfile
import os
from typing import Dict, Any, List, Optional

from .base import BaseConnector, ConnectorDocument
from .google_drive import GoogleDriveConnector
from .connection_manager import ConnectionManager


class ConnectorService:
    """Service to manage document connectors and process files"""
    
    def __init__(self, opensearch_client, patched_async_client, process_pool, embed_model: str, index_name: str, task_service=None):
        self.opensearch = opensearch_client
        self.openai_client = patched_async_client
        self.process_pool = process_pool
        self.embed_model = embed_model
        self.index_name = index_name
        self.task_service = task_service
        self.connection_manager = ConnectionManager()
    
    async def initialize(self):
        """Initialize the service by loading existing connections"""
        await self.connection_manager.load_connections()
    
    async def get_connector(self, connection_id: str) -> Optional[BaseConnector]:
        """Get a connector by connection ID"""
        return await self.connection_manager.get_connector(connection_id)
    
    async def process_connector_document(self, document: ConnectorDocument, owner_user_id: str) -> Dict[str, Any]:
        """Process a document from a connector using existing processing pipeline"""
        
        # Create temporary file from document content
        with tempfile.NamedTemporaryFile(delete=False, suffix=self._get_file_extension(document.mimetype)) as tmp_file:
            tmp_file.write(document.content)
            tmp_file.flush()
            
            try:
                # Use existing process_file_common function with connector document metadata
                # We'll use the document service's process_file_common method
                from services.document_service import DocumentService
                doc_service = DocumentService()
                
                # Process using the existing pipeline but with connector document metadata
                result = await doc_service.process_file_common(
                    file_path=tmp_file.name, 
                    file_hash=document.id,  # Use connector document ID as hash
                    owner_user_id=owner_user_id,
                    original_filename=document.filename  # Pass the original Google Doc title
                )
                
                # If successfully indexed, update the indexed documents with connector metadata
                if result["status"] == "indexed":
                    # Update all chunks with connector-specific metadata
                    await self._update_connector_metadata(document, owner_user_id)
                
                return {
                    **result,
                    "filename": document.filename,
                    "source_url": document.source_url
                }
                
            finally:
                # Clean up temporary file
                os.unlink(tmp_file.name)
    
    async def _update_connector_metadata(self, document: ConnectorDocument, owner_user_id: str):
        """Update indexed chunks with connector-specific metadata"""
        # Find all chunks for this document
        query = {
            "query": {
                "term": {"document_id": document.id}
            }
        }
        
        response = await self.opensearch.search(index=self.index_name, body=query)
        
        # Update each chunk with connector metadata
        for hit in response["hits"]["hits"]:
            chunk_id = hit["_id"]
            update_body = {
                "doc": {
                    "source_url": document.source_url,
                    "connector_type": "google_drive",  # Could be passed as parameter
                    # Additional ACL info beyond owner (already set by process_file_common)
                    "allowed_users": document.acl.allowed_users,
                    "allowed_groups": document.acl.allowed_groups,
                    "user_permissions": document.acl.user_permissions,
                    "group_permissions": document.acl.group_permissions,
                    # Timestamps
                    "created_time": document.created_time.isoformat(),
                    "modified_time": document.modified_time.isoformat(),
                    # Additional metadata
                    "metadata": document.metadata
                }
            }
            
            await self.opensearch.update(index=self.index_name, id=chunk_id, body=update_body)
    
    def _get_file_extension(self, mimetype: str) -> str:
        """Get file extension based on MIME type"""
        mime_to_ext = {
            'application/pdf': '.pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
            'application/msword': '.doc',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
            'application/vnd.ms-powerpoint': '.ppt',
            'text/plain': '.txt',
            'text/html': '.html',
            'application/rtf': '.rtf',
            'application/vnd.google-apps.document': '.pdf',  # Exported as PDF
            'application/vnd.google-apps.presentation': '.pdf',
            'application/vnd.google-apps.spreadsheet': '.pdf',
        }
        return mime_to_ext.get(mimetype, '.bin')
    
    async def sync_connector_files(self, connection_id: str, user_id: str, max_files: int = None) -> str:
        """Sync files from a connector connection using existing task tracking system"""
        if not self.task_service:
            raise ValueError("TaskService not available - connector sync requires task service dependency")
            
        print(f"[DEBUG] Starting sync for connection {connection_id}, max_files={max_files}")
        
        connector = await self.get_connector(connection_id)
        if not connector:
            raise ValueError(f"Connection '{connection_id}' not found or not authenticated")
        
        print(f"[DEBUG] Got connector, authenticated: {connector.is_authenticated}")
        
        if not connector.is_authenticated:
            raise ValueError(f"Connection '{connection_id}' not authenticated")
        
        # Collect files to process (limited by max_files)
        files_to_process = []
        page_token = None
        
        # Calculate page size to minimize API calls
        page_size = min(max_files or 100, 1000) if max_files else 100
        
        while True:
            # List files from connector with limit
            print(f"[DEBUG] Calling list_files with page_size={page_size}, page_token={page_token}")
            file_list = await connector.list_files(page_token, limit=page_size)
            print(f"[DEBUG] Got {len(file_list.get('files', []))} files")
            files = file_list['files']
            
            if not files:
                break
                
            for file_info in files:
                if max_files and len(files_to_process) >= max_files:
                    break
                files_to_process.append(file_info)
            
            # Stop if we have enough files or no more pages
            if (max_files and len(files_to_process) >= max_files) or not file_list.get('nextPageToken'):
                break
                
            page_token = file_list.get('nextPageToken')
        
        if not files_to_process:
            raise ValueError("No files found to sync")
        
        # Create custom processor for connector files
        from models.processors import ConnectorFileProcessor
        processor = ConnectorFileProcessor(self, connection_id, files_to_process, user_id)
        
        # Use file IDs as items (no more fake file paths!)
        file_ids = [file_info['id'] for file_info in files_to_process]
        
        # Create custom task using TaskService
        task_id = await self.task_service.create_custom_task(user_id, file_ids, processor)
        
        return task_id
    
    async def sync_specific_files(self, connection_id: str, user_id: str, file_ids: List[str]) -> str:
        """Sync specific files by their IDs (used for webhook-triggered syncs)"""
        if not self.task_service:
            raise ValueError("TaskService not available - connector sync requires task service dependency")
            
        connector = await self.get_connector(connection_id)
        if not connector:
            raise ValueError(f"Connection '{connection_id}' not found or not authenticated")
        
        if not connector.is_authenticated:
            raise ValueError(f"Connection '{connection_id}' not authenticated")
        
        if not file_ids:
            raise ValueError("No file IDs provided")
        
        # Create custom processor for specific connector files
        from models.processors import ConnectorFileProcessor
        # We'll pass file_ids as the files_info, the processor will handle ID-only files
        processor = ConnectorFileProcessor(self, connection_id, file_ids, user_id)
        
        # Create custom task using TaskService
        task_id = await self.task_service.create_custom_task(user_id, file_ids, processor)
        
        return task_id
    
    async def _get_connector(self, connection_id: str) -> Optional[BaseConnector]:
        """Get a connector by connection ID (alias for get_connector)"""
        return await self.get_connector(connection_id)