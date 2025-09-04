import asyncio
import tempfile
import os
from typing import Dict, Any, List, Optional

from .base import BaseConnector, ConnectorDocument
from .google_drive import GoogleDriveConnector
from .sharepoint import SharePointConnector
from .onedrive import OneDriveConnector
from .connection_manager import ConnectionManager


class ConnectorService:
    """Service to manage document connectors and process files"""

    def __init__(
        self,
        patched_async_client,
        process_pool,
        embed_model: str,
        index_name: str,
        task_service=None,
        session_manager=None,
    ):
        self.openai_client = patched_async_client
        self.process_pool = process_pool
        self.embed_model = embed_model
        self.index_name = index_name
        self.task_service = task_service
        self.session_manager = session_manager
        self.connection_manager = ConnectionManager()

    async def initialize(self):
        """Initialize the service by loading existing connections"""
        await self.connection_manager.load_connections()

    async def get_connector(self, connection_id: str) -> Optional[BaseConnector]:
        """Get a connector by connection ID"""
        return await self.connection_manager.get_connector(connection_id)

    async def process_connector_document(
        self,
        document: ConnectorDocument,
        owner_user_id: str,
        connector_type: str,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
    ) -> Dict[str, Any]:
        """Process a document from a connector using existing processing pipeline"""

        # Create temporary file from document content
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=self._get_file_extension(document.mimetype)
        ) as tmp_file:
            tmp_file.write(document.content)
            tmp_file.flush()

            try:
                # Use existing process_file_common function with connector document metadata
                # We'll use the document service's process_file_common method
                from services.document_service import DocumentService

                doc_service = DocumentService(session_manager=self.session_manager)

                print(f"[DEBUG] Processing connector document with ID: {document.id}")

                # Process using the existing pipeline but with connector document metadata
                result = await doc_service.process_file_common(
                    file_path=tmp_file.name,
                    file_hash=document.id,  # Use connector document ID as hash
                    owner_user_id=owner_user_id,
                    original_filename=document.filename,  # Pass the original Google Doc title
                    jwt_token=jwt_token,
                    owner_name=owner_name,
                    owner_email=owner_email,
                    file_size=len(document.content) if document.content else 0,
                    connector_type=connector_type,
                )

                print(f"[DEBUG] Document processing result: {result}")

                # If successfully indexed or already exists, update the indexed documents with connector metadata
                if result["status"] in ["indexed", "unchanged"]:
                    # Update all chunks with connector-specific metadata
                    await self._update_connector_metadata(
                        document, owner_user_id, connector_type, jwt_token
                    )

                return {
                    **result,
                    "filename": document.filename,
                    "source_url": document.source_url,
                }

            finally:
                # Clean up temporary file
                os.unlink(tmp_file.name)

    async def _update_connector_metadata(
        self,
        document: ConnectorDocument,
        owner_user_id: str,
        connector_type: str,
        jwt_token: str = None,
    ):
        """Update indexed chunks with connector-specific metadata"""
        print(f"[DEBUG] Looking for chunks with document_id: {document.id}")

        # Find all chunks for this document
        query = {"query": {"term": {"document_id": document.id}}}

        # Get user's OpenSearch client
        opensearch_client = self.session_manager.get_user_opensearch_client(
            owner_user_id, jwt_token
        )

        try:
            response = await opensearch_client.search(index=self.index_name, body=query)
        except Exception as e:
            print(
                f"[ERROR] OpenSearch search failed for connector metadata update: {e}"
            )
            print(f"[ERROR] Search query: {query}")
            raise

        print(f"[DEBUG] Search query: {query}")
        print(
            f"[DEBUG] Found {len(response['hits']['hits'])} chunks matching document_id: {document.id}"
        )

        # Update each chunk with connector metadata
        print(
            f"[DEBUG] Updating {len(response['hits']['hits'])} chunks with connector_type: {connector_type}"
        )
        for hit in response["hits"]["hits"]:
            chunk_id = hit["_id"]
            current_connector_type = hit["_source"].get("connector_type", "unknown")
            print(
                f"[DEBUG] Chunk {chunk_id}: current connector_type = {current_connector_type}, updating to {connector_type}"
            )

            update_body = {
                "doc": {
                    "source_url": document.source_url,
                    "connector_type": connector_type,  # Override the "local" set by process_file_common
                    # Additional ACL info beyond owner (already set by process_file_common)
                    "allowed_users": document.acl.allowed_users,
                    "allowed_groups": document.acl.allowed_groups,
                    "user_permissions": document.acl.user_permissions,
                    "group_permissions": document.acl.group_permissions,
                    # Timestamps
                    "created_time": document.created_time.isoformat()
                    if document.created_time
                    else None,
                    "modified_time": document.modified_time.isoformat()
                    if document.modified_time
                    else None,
                    # Additional metadata
                    "metadata": document.metadata,
                }
            }

            try:
                await opensearch_client.update(
                    index=self.index_name, id=chunk_id, body=update_body
                )
                print(f"[DEBUG] Updated chunk {chunk_id} with connector metadata")
            except Exception as e:
                print(f"[ERROR] OpenSearch update failed for chunk {chunk_id}: {e}")
                print(f"[ERROR] Update body: {update_body}")
                raise

    def _get_file_extension(self, mimetype: str) -> str:
        """Get file extension based on MIME type"""
        mime_to_ext = {
            "application/pdf": ".pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/msword": ".doc",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
            "application/vnd.ms-powerpoint": ".ppt",
            "text/plain": ".txt",
            "text/html": ".html",
            "application/rtf": ".rtf",
            "application/vnd.google-apps.document": ".pdf",  # Exported as PDF
            "application/vnd.google-apps.presentation": ".pdf",
            "application/vnd.google-apps.spreadsheet": ".pdf",
        }
        return mime_to_ext.get(mimetype, ".bin")

    async def sync_connector_files(
        self,
        connection_id: str,
        user_id: str,
        max_files: int = None,
        jwt_token: str = None,
        selected_files: List[str] = None,
        selected_folders: List[str] = None,
    ) -> str:
        """Sync files from a connector connection using existing task tracking system"""
        if not self.task_service:
            raise ValueError(
                "TaskService not available - connector sync requires task service dependency"
            )

        print(
            f"[DEBUG] Starting sync for connection {connection_id}, max_files={max_files}"
        )

        connector = await self.get_connector(connection_id)
        if not connector:
            raise ValueError(
                f"Connection '{connection_id}' not found or not authenticated"
            )

        print(f"[DEBUG] Got connector, authenticated: {connector.is_authenticated}")

        if not connector.is_authenticated:
            raise ValueError(f"Connection '{connection_id}' not authenticated")

        # Get user information
        user = self.session_manager.get_user(user_id) if self.session_manager else None
        owner_name = user.name if user else None
        owner_email = user.email if user else None

        # Create custom processor for connector files
        from models.processors import ConnectorFileProcessor

        processor = ConnectorFileProcessor(
            self,
            connection_id,
            selected_files,
            user_id,
            jwt_token=jwt_token,
            owner_name=owner_name,
            owner_email=owner_email,
        )

        # Create custom task using TaskService
        task_id = await self.task_service.create_custom_task(
            user_id, selected_files, processor
        )

        return task_id

    async def sync_specific_files(
        self,
        connection_id: str,
        user_id: str,
        file_ids: List[str],
        jwt_token: str = None,
    ) -> str:
        """Sync specific files by their IDs (used for webhook-triggered syncs)"""
        if not self.task_service:
            raise ValueError(
                "TaskService not available - connector sync requires task service dependency"
            )

        connector = await self.get_connector(connection_id)
        if not connector:
            raise ValueError(
                f"Connection '{connection_id}' not found or not authenticated"
            )

        if not connector.is_authenticated:
            raise ValueError(f"Connection '{connection_id}' not authenticated")

        if not file_ids:
            raise ValueError("No file IDs provided")

        # Get user information
        user = self.session_manager.get_user(user_id) if self.session_manager else None
        owner_name = user.name if user else None
        owner_email = user.email if user else None

        # Create custom processor for specific connector files
        from models.processors import ConnectorFileProcessor

        # We'll pass file_ids as the files_info, the processor will handle ID-only files
        processor = ConnectorFileProcessor(
            self,
            connection_id,
            file_ids,
            user_id,
            jwt_token=jwt_token,
            owner_name=owner_name,
            owner_email=owner_email,
        )

        # Create custom task using TaskService
        task_id = await self.task_service.create_custom_task(
            user_id, file_ids, processor
        )

        return task_id

    async def _get_connector(self, connection_id: str) -> Optional[BaseConnector]:
        """Get a connector by connection ID (alias for get_connector)"""
        return await self.get_connector(connection_id)
