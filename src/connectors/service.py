from typing import Any, Dict, List, Optional

from utils.logging_config import get_logger

from .base import BaseConnector, ConnectorDocument
from .connection_manager import ConnectionManager


logger = get_logger(__name__)


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
        self.clients = patched_async_client  # Store the clients object to access the property
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
        from utils.file_utils import auto_cleanup_tempfile

        with auto_cleanup_tempfile(
            suffix=self._get_file_extension(document.mimetype)
        ) as tmp_path:
            # Write document content to temp file
            with open(tmp_path, "wb") as f:
                f.write(document.content)

            # Use existing process_file_common function with connector document metadata
            # We'll use the document service's process_file_common method
            from services.document_service import DocumentService

            doc_service = DocumentService(session_manager=self.session_manager)

            logger.debug("Processing connector document", document_id=document.id)

            # Process using consolidated processing pipeline
            from models.processors import TaskProcessor

            processor = TaskProcessor(document_service=doc_service)
            result = await processor.process_document_standard(
                file_path=tmp_path,
                file_hash=document.id,  # Use connector document ID as hash
                owner_user_id=owner_user_id,
                original_filename=document.filename,  # Pass the original Google Doc title
                jwt_token=jwt_token,
                owner_name=owner_name,
                owner_email=owner_email,
                file_size=len(document.content) if document.content else 0,
                connector_type=connector_type,
            )

            logger.debug("Document processing result", result=result)

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

    async def _update_connector_metadata(
        self,
        document: ConnectorDocument,
        owner_user_id: str,
        connector_type: str,
        jwt_token: str = None,
    ):
        """Update indexed chunks with connector-specific metadata"""
        logger.debug("Looking for chunks", document_id=document.id)

        # Find all chunks for this document
        query = {"query": {"term": {"document_id": document.id}}}

        # Get user's OpenSearch client
        opensearch_client = self.session_manager.get_user_opensearch_client(
            owner_user_id, jwt_token
        )

        try:
            response = await opensearch_client.search(index=self.index_name, body=query)
        except Exception as e:
            logger.error(
                "OpenSearch search failed for connector metadata update",
                error=str(e),
                query=query,
            )
            raise

        logger.debug(
            "Search query executed",
            query=query,
            chunks_found=len(response["hits"]["hits"]),
            document_id=document.id,
        )

        # Update each chunk with connector metadata
        logger.debug(
            "Updating chunks with connector_type",
            chunk_count=len(response["hits"]["hits"]),
            connector_type=connector_type,
        )
        for hit in response["hits"]["hits"]:
            chunk_id = hit["_id"]
            current_connector_type = hit["_source"].get("connector_type", "unknown")
            logger.debug(
                "Updating chunk connector metadata",
                chunk_id=chunk_id,
                current_connector_type=current_connector_type,
                new_connector_type=connector_type,
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
                logger.debug("Updated chunk with connector metadata", chunk_id=chunk_id)
            except Exception as e:
                logger.error(
                    "OpenSearch update failed for chunk",
                    chunk_id=chunk_id,
                    error=str(e),
                    update_body=update_body,
                )
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
    ) -> str:
        """Sync files from a connector connection using existing task tracking system"""
        if not self.task_service:
            raise ValueError(
                "TaskService not available - connector sync requires task service dependency"
            )

        logger.debug(
            "Starting sync for connection",
            connection_id=connection_id,
            max_files=max_files,
        )

        connector = await self.get_connector(connection_id)
        if not connector:
            raise ValueError(
                f"Connection '{connection_id}' not found or not authenticated"
            )

        logger.debug("Got connector", authenticated=connector.is_authenticated)

        if not connector.is_authenticated:
            raise ValueError(f"Connection '{connection_id}' not authenticated")

        # Collect files to process (limited by max_files)
        files_to_process = []
        page_token = None

        # Calculate page size to minimize API calls
        page_size = min(max_files or 100, 1000) if max_files else 100

        while True:
            # List files from connector with limit
            logger.debug(
                "Calling list_files", page_size=page_size, page_token=page_token
            )
            file_list = await connector.list_files(page_token, limit=page_size)
            logger.debug(
                "Got files from connector", file_count=len(file_list.get("files", []))
            )
            files = file_list["files"]

            if not files:
                break

            for file_info in files:
                if max_files and len(files_to_process) >= max_files:
                    break
                files_to_process.append(file_info)

            # Stop if we have enough files or no more pages
            if (max_files and len(files_to_process) >= max_files) or not file_list.get(
                "nextPageToken"
            ):
                break

            page_token = file_list.get("nextPageToken")

        # Get user information
        user = self.session_manager.get_user(user_id) if self.session_manager else None
        owner_name = user.name if user else None
        owner_email = user.email if user else None

        # Create custom processor for connector files
        from models.processors import ConnectorFileProcessor
        from services.document_service import DocumentService

        processor = ConnectorFileProcessor(
            self,
            connection_id,
            files_to_process,
            user_id,
            jwt_token=jwt_token,
            owner_name=owner_name,
            owner_email=owner_email,
            document_service=(
                self.task_service.document_service
                if self.task_service and self.task_service.document_service
                else DocumentService(session_manager=self.session_manager)
            ),
        )

        # Use file IDs as items (no more fake file paths!)
        file_ids = [file_info["id"] for file_info in files_to_process]

        # Create custom task using TaskService
        task_id = await self.task_service.create_custom_task(
            user_id, file_ids, processor
        )

        return task_id

    async def sync_specific_files(
        self,
        connection_id: str,
        user_id: str,
        file_ids: List[str],
        jwt_token: str = None,
    ) -> str:
        """
        Sync specific files by their IDs (used for webhook-triggered syncs or manual selection).
        Automatically expands folders to their contents.
        """
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

        # Temporarily set file_ids in the connector's config so list_files() can use them
        # Store the original values to restore later
        original_file_ids = None
        original_folder_ids = None

        if hasattr(connector, "cfg"):
            original_file_ids = getattr(connector.cfg, "file_ids", None)
            original_folder_ids = getattr(connector.cfg, "folder_ids", None)

        try:
            # Set the file_ids we want to sync in the connector's config
            if hasattr(connector, "cfg"):
                connector.cfg.file_ids = file_ids  # type: ignore
                connector.cfg.folder_ids = None  # type: ignore

            # Get the expanded list of file IDs (folders will be expanded to their contents)
            # This uses the connector's list_files() which calls _iter_selected_items()
            result = await connector.list_files()
            expanded_file_ids = [f["id"] for f in result.get("files", [])]

            if not expanded_file_ids:
                logger.warning(
                    f"No files found after expanding file_ids. "
                    f"Original IDs: {file_ids}. This may indicate all IDs were folders "
                    f"with no contents, or files that were filtered out."
                )
                # Return empty task rather than failing
                raise ValueError("No files to sync after expanding folders")

        except Exception as e:
            logger.error(f"Failed to expand file_ids via list_files(): {e}")
            # Fallback to original file_ids if expansion fails
            expanded_file_ids = file_ids
        finally:
            # Restore original config values
            if hasattr(connector, "cfg"):
                connector.cfg.file_ids = original_file_ids  # type: ignore
                connector.cfg.folder_ids = original_folder_ids  # type: ignore

        # Create custom processor for specific connector files
        from models.processors import ConnectorFileProcessor
        from services.document_service import DocumentService

        # Use expanded_file_ids which has folders already expanded
        processor = ConnectorFileProcessor(
            self,
            connection_id,
            expanded_file_ids,
            user_id,
            jwt_token=jwt_token,
            owner_name=owner_name,
            owner_email=owner_email,
            document_service=(
                self.task_service.document_service
                if self.task_service and self.task_service.document_service
                else DocumentService(session_manager=self.session_manager)
            ),
        )

        # Create custom task using TaskService
        task_id = await self.task_service.create_custom_task(
            user_id, expanded_file_ids, processor
        )

        return task_id

    async def _get_connector(self, connection_id: str) -> Optional[BaseConnector]:
        """Get a connector by connection ID (alias for get_connector)"""
        return await self.get_connector(connection_id)
