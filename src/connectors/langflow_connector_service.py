from typing import Any, Dict, List, Optional

# Create custom processor for connector files using Langflow
from models.processors import LangflowConnectorFileProcessor
from services.langflow_file_service import LangflowFileService
from utils.logging_config import get_logger

from .base import BaseConnector, ConnectorDocument
from .connection_manager import ConnectionManager
from utils.file_utils import get_file_extension, clean_connector_filename

logger = get_logger(__name__)


class LangflowConnectorService:
    """Service to manage connector documents and process them via Langflow"""

    def __init__(
        self,
        task_service=None,
        session_manager=None,
    ):
        self.task_service = task_service
        self.session_manager = session_manager
        self.connection_manager = ConnectionManager()

        # Initialize LangflowFileService for processing connector documents
        self.langflow_service = LangflowFileService()

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
        """Process a document from a connector using LangflowFileService pattern"""

        logger.debug(
            "Processing connector document via Langflow",
            document_id=document.id,
            filename=document.filename,
        )

        from utils.file_utils import auto_cleanup_tempfile

        suffix = get_file_extension(document.mimetype)

        # Create temporary file from document content
        with auto_cleanup_tempfile(suffix=suffix) as tmp_path:
            # Write document content to temp file
            with open(tmp_path, "wb") as f:
                f.write(document.content)

            # Step 1: Upload file to Langflow
            logger.debug("Uploading file to Langflow", filename=document.filename)
            content = document.content
            
            # Clean filename and ensure we don't add a double extension
            processed_filename = clean_connector_filename(document.filename, document.mimetype)

            file_tuple = (
                processed_filename,
                content,
                document.mimetype or "application/octet-stream",
            )

            # Step 0: Delete existing chunks for this file before re-ingesting
            # This prevents duplicate chunks when syncing files
            if self.session_manager:
                try:
                    from config.settings import get_index_name
                    opensearch_client = self.session_manager.get_user_opensearch_client(owner_user_id, jwt_token)
                    delete_body = {"query": {"term": {"filename": processed_filename}}}
                    delete_result = await opensearch_client.delete_by_query(index=get_index_name(), body=delete_body)
                    deleted_count = delete_result.get("deleted", 0)
                    logger.info("Deleted existing chunks before re-ingestion", filename=processed_filename, deleted_count=deleted_count)
                except Exception as delete_err:
                    logger.warning("Failed to delete existing chunks before re-ingestion", filename=processed_filename, error=str(delete_err))

            langflow_file_id = None  # Initialize to track if upload succeeded
            try:
                upload_result = await self.langflow_service.upload_user_file(
                    file_tuple, jwt_token
                )
                langflow_file_id = upload_result["id"]
                langflow_file_path = upload_result["path"]

                logger.debug(
                    "File uploaded to Langflow",
                    file_id=langflow_file_id,
                    path=langflow_file_path,
                )

                # Step 2: Run ingestion flow with the uploaded file
                logger.debug(
                    "Running Langflow ingestion flow", file_path=langflow_file_path
                )

                # Use the same tweaks pattern as LangflowFileService
                tweaks = {}  # Let Langflow handle the ingestion with default settings

                # Extract ACL information from the connector document, if available
                allowed_users: list[str] = []
                allowed_groups: list[str] = []
                if getattr(document, "acl", None) is not None:
                    try:
                        allowed_users = document.acl.allowed_users or []
                        allowed_groups = document.acl.allowed_groups or []
                    except AttributeError:
                        # If ACL shape is different or missing fields, fall back to empty lists
                        allowed_users = []
                        allowed_groups = []

                ingestion_result = await self.langflow_service.run_ingestion_flow(
                    file_paths=[langflow_file_path],
                    file_tuples=[file_tuple],
                    jwt_token=jwt_token,
                    tweaks=tweaks,
                    owner=owner_user_id,
                    owner_name=owner_name,
                    owner_email=owner_email,
                    connector_type=connector_type,
                    document_id=document.id,
                    source_url=document.source_url,
                    allowed_users=allowed_users,
                    allowed_groups=allowed_groups,
                )

                logger.debug("Ingestion flow completed", result=ingestion_result)

                # Step 3: Delete the file from Langflow
                logger.debug("Deleting file from Langflow", file_id=langflow_file_id)
                await self.langflow_service.delete_user_file(langflow_file_id)
                logger.debug("File deleted from Langflow", file_id=langflow_file_id)

                return {
                    "status": "indexed",
                    "filename": document.filename,
                    "source_url": document.source_url,
                    "document_id": document.id,
                    "connector_type": connector_type,
                    "langflow_result": ingestion_result,
                }

            except Exception as e:
                logger.error(
                    "Failed to process connector document via Langflow",
                    document_id=document.id,
                    error=str(e),
                )
                # Try to clean up Langflow file if upload succeeded but processing failed
                if langflow_file_id is not None:
                    try:
                        await self.langflow_service.delete_user_file(langflow_file_id)
                        logger.debug(
                            "Cleaned up Langflow file after error",
                            file_id=langflow_file_id,
                        )
                    except Exception as cleanup_error:
                        logger.warning(
                            "Failed to cleanup Langflow file",
                            file_id=langflow_file_id,
                            error=str(cleanup_error),
                        )
                raise


    async def sync_connector_files(
        self,
        connection_id: str,
        user_id: str,
        max_files: int = None,
        jwt_token: str = None,
    ) -> str:
        """Sync files from a connector connection using Langflow processing"""
        if not self.task_service:
            raise ValueError(
                "TaskService not available - connector sync requires task service dependency"
            )

        logger.debug(
            "Starting Langflow-based sync for connection",
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

        processor = LangflowConnectorFileProcessor(
            self,
            connection_id,
            files_to_process,
            user_id,
            jwt_token=jwt_token,
            owner_name=owner_name,
            owner_email=owner_email,
        )

        # Use file IDs as items
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
        Sync specific files by their IDs using Langflow processing.
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
        cfg = getattr(connector, "cfg", None)
        original_file_ids = None
        original_folder_ids = None

        if cfg is not None:
            original_file_ids = getattr(cfg, "file_ids", None)
            original_folder_ids = getattr(cfg, "folder_ids", None)

        expanded_file_ids = file_ids  # Default to original IDs
        
        try:
            # Set the file_ids we want to sync in the connector's config
            if cfg is not None:
                cfg.file_ids = file_ids  # type: ignore
                cfg.folder_ids = None  # type: ignore

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
            if cfg is not None:
                cfg.file_ids = original_file_ids  # type: ignore
                cfg.folder_ids = original_folder_ids  # type: ignore

        processor = LangflowConnectorFileProcessor(
            self,
            connection_id,
            expanded_file_ids,
            user_id,
            jwt_token=jwt_token,
            owner_name=owner_name,
            owner_email=owner_email,
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
