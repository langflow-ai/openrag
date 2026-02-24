from typing import Any, Dict, List, Optional

from utils.logging_config import get_logger

from .base import BaseConnector, ConnectorDocument
from .connection_manager import ConnectionManager
from utils.file_utils import get_file_extension, clean_connector_filename


logger = get_logger(__name__)


class ConnectorService:
    """Service to manage document connectors and process files"""

    def __init__(
        self,
        patched_async_client,
        embed_model: str,
        index_name: str,
        task_service=None,
        session_manager=None,
    ):
        self.clients = patched_async_client
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
            suffix=get_file_extension(document.mimetype)
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
                acl=document.acl,
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
        from utils.acl_utils import update_document_acl

        logger.debug("Looking for chunks", document_id=document.id)

        # Get user's OpenSearch client
        opensearch_client = self.session_manager.get_user_opensearch_client(
            owner_user_id, jwt_token
        )

        # Update ACL if changed (hash-based skip optimization)
        acl_result = await update_document_acl(
            document_id=document.id,
            acl=document.acl,
            opensearch_client=opensearch_client,
        )

        # Log ACL update result
        if acl_result["status"] == "unchanged":
            logger.debug(f"ACL unchanged for {document.id}, skipped update")
        elif acl_result["status"] == "updated":
            logger.info(
                f"Updated ACL for {document.id}, "
                f"{acl_result['chunks_updated']} chunks updated"
            )
        elif acl_result["status"] == "error":
            logger.error(f"ACL update error for {document.id}: {acl_result.get('error')}")

        # Update other metadata fields (source_url, timestamps, etc.)
        # Use update_by_query for efficiency
        try:
            await opensearch_client.update_by_query(
                index=self.index_name,
                body={
                    "query": {"term": {"document_id": document.id}},
                    "script": {
                        "source": """
                            ctx._source.source_url = params.source_url;
                            ctx._source.connector_type = params.connector_type;
                            if (params.created_time != null) {
                                ctx._source.created_time = params.created_time;
                            }
                            if (params.modified_time != null) {
                                ctx._source.modified_time = params.modified_time;
                            }
                            if (params.metadata != null) {
                                ctx._source.metadata = params.metadata;
                            }
                        """,
                        "params": {
                            "source_url": document.source_url,
                            "connector_type": connector_type,
                            "created_time": document.created_time.isoformat()
                            if document.created_time
                            else None,
                            "modified_time": document.modified_time.isoformat()
                            if document.modified_time
                            else None,
                            "metadata": document.metadata,
                        }
                    }
                }
            )
            logger.debug(f"Updated metadata for document {document.id}")
        except Exception as e:
            logger.error(
                "OpenSearch metadata update failed",
                document_id=document.id,
                error=str(e),
            )
            raise


    async def sync_connector_files(
        self,
        connection_id: str,
        user_id: str,
        max_files: int = None,
        jwt_token: str = None,
        filename_filter: set = None,
    ) -> str:
        """
        Sync files from a connector connection using existing task tracking system.
        
        Args:
            connection_id: The connection ID
            user_id: The user ID
            max_files: Maximum number of files to sync
            jwt_token: Optional JWT token
            filename_filter: Optional set of filenames to filter - only files with names
                           in this set will be synced. Used to prevent deleted files
                           from being re-synced.
        """
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
                # Filter by filename if filter is provided
                if filename_filter is not None:
                    file_name = file_info.get("name", "")
                    if file_name not in filename_filter:
                        logger.debug(
                            "Skipping file not in filter",
                            filename=file_name,
                        )
                        continue
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
        original_filenames = {
            file_info["id"]: clean_connector_filename(
                file_info["name"], file_info.get("mimeType") or file_info.get("mimetype")
            )
            for file_info in files_to_process
            if "name" in file_info
        }

        # Create custom task using TaskService
        task_id = await self.task_service.create_custom_task(
            user_id, file_ids, processor, original_filenames=original_filenames
        )

        return task_id

    async def sync_specific_files(
        self,
        connection_id: str,
        user_id: str,
        file_ids: List[str],
        jwt_token: str = None,
        file_infos: List[Dict[str, Any]] = None,
    ) -> str:
        """
        Sync specific files by their IDs (used for webhook-triggered syncs or manual selection).
        Automatically expands folders to their contents.
        
        Args:
            connection_id: The connection ID
            user_id: The user ID
            file_ids: List of file IDs to sync
            jwt_token: Optional JWT token for authentication
            file_infos: Optional list of file info dicts with {id, name, mimeType, downloadUrl, size}
                       When provided, download URLs can be used directly without Graph API calls.
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

        # If file_infos provided, cache them in the connector for later use
        # This allows get_file_content to use download URLs directly
        if file_infos and hasattr(connector, 'set_file_infos'):
            connector.set_file_infos(file_infos)
            logger.info(f"Cached {len(file_infos)} file infos with download URLs in connector")

        # Temporarily set file_ids in the connector's config so list_files() can use them
        # Store the original values to restore later
        original_file_ids = None
        original_folder_ids = None

        if hasattr(connector, "cfg"):
            original_file_ids = getattr(connector.cfg, "file_ids", None)
            original_folder_ids = getattr(connector.cfg, "folder_ids", None)

        expanded_file_ids = file_ids  # Default to original IDs

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
                # If we have file_infos with download URLs, use original file_ids
                # (OneDrive sharing IDs can't be expanded but can be downloaded directly)
                if file_infos:
                    logger.info("Using original file IDs with cached download URLs")
                    expanded_file_ids = file_ids
                else:
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
        original_filenames = {}
        if file_infos:
            original_filenames = {
                f["id"]: clean_connector_filename(
                    f["name"], f.get("mimeType") or f.get("mimetype")
                )
                for f in file_infos
                if "id" in f and "name" in f
            }

        task_id = await self.task_service.create_custom_task(
            user_id, expanded_file_ids, processor, original_filenames=original_filenames
        )

        return task_id

    async def _get_connector(self, connection_id: str) -> Optional[BaseConnector]:
        """Get a connector by connection ID (alias for get_connector)"""
        return await self.get_connector(connection_id)
