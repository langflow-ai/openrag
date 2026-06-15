from typing import Any

from utils.file_utils import clean_connector_filename, get_file_extension
from utils.logging_config import get_logger

from .base import BaseConnector, ConnectorDocument
from .connection_manager import ConnectionManager

logger = get_logger(__name__)


class ConnectorService:
    """Service to manage document connectors and process files"""

    def __init__(
        self,
        patched_async_client=None,
        embed_model: str = "",
        index_name: str = "",
        task_service=None,
        session_manager=None,
        models_service=None,
        document_service=None,
        docling_service=None,
        flows_service=None,
        langflow_service=None,
    ):
        self.clients = patched_async_client
        self.embed_model = embed_model
        self.index_name = index_name
        self.task_service = task_service
        self.session_manager = session_manager
        self.connection_manager = ConnectionManager()
        self.models_service = models_service
        self.document_service = document_service
        self.docling_service = docling_service
        self.flows_service = flows_service
        self.langflow_service = langflow_service

    async def initialize(self):
        """Initialize the service by loading existing connections"""
        await self.connection_manager.load_connections()

    async def get_connector(self, connection_id: str) -> BaseConnector | None:
        """Get a connector by connection ID"""
        return await self.connection_manager.get_connector(connection_id)

    async def _get_effective_sync_jwt(
        self,
        user_id: str,
        jwt_token: str | None = None,
    ) -> str | None:
        """Return a current OpenSearch JWT for connector sync work."""
        if not self.session_manager:
            return jwt_token

        user = self.session_manager.get_user(user_id)
        if user is None and user_id:
            from session_manager import User

            user = User(
                user_id=user_id,
                email=user_id,
                name=user_id,
                provider="connector",
            )
            self.session_manager.users[user_id] = user
        if user is None:
            return self.session_manager.get_effective_jwt_token(user_id, jwt_token)

        effective_token = jwt_token or user.jwt_token
        if (
            effective_token is None
            and getattr(self.session_manager, "private_key", None) is not None
        ):
            return self.session_manager.create_jwt_token(user)
        return self.session_manager.get_effective_jwt_token(user.user_id, effective_token)

    async def process_connector_document(
        self,
        document: ConnectorDocument,
        owner_user_id: str,
        connector_type: str,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        ingest_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Process a document from a connector using active processing pipeline"""
        jwt_token = await self._get_effective_sync_jwt(owner_user_id, jwt_token)

        from config.settings import DISABLE_INGEST_WITH_LANGFLOW

        if not DISABLE_INGEST_WITH_LANGFLOW and self.langflow_service is not None:
            # Process via Langflow pipeline
            from utils.file_utils import langflow_safe_filename_and_mimetype

            langflow_filename, processed_mimetype = langflow_safe_filename_and_mimetype(
                document.filename, document.mimetype
            )
            file_tuple = (langflow_filename, document.content, processed_mimetype)

            allowed_users = []
            allowed_groups = []
            allowed_principals = []
            allowed_principal_labels = []
            if document.acl:
                try:
                    allowed_users = document.acl.allowed_users or []
                    allowed_groups = document.acl.allowed_groups or []
                    allowed_principals = document.acl.allowed_principals or []
                    allowed_principal_labels = document.acl.allowed_principal_labels or []
                except AttributeError:
                    pass

            connector_tweak_settings = None
            if isinstance(ingest_settings, dict):
                connector_tweak_settings = dict(ingest_settings)
                connector_tweak_settings.pop("embeddingModel", None)

            tweaks = self.langflow_service.merge_ui_ingest_settings_into_tweaks(
                {}, connector_tweak_settings
            )

            result = await self.langflow_service.upload_and_ingest_file(
                file_tuple=file_tuple,
                session_id=None,
                tweaks=tweaks,
                settings=ingest_settings,
                jwt_token=jwt_token,
                owner=owner_user_id,
                owner_name=owner_name,
                owner_email=owner_email,
                connector_type=connector_type,
                docling_polling_service=self.task_service.docling_polling_service
                if self.task_service
                else None,
                document_id=document.id,
                source_url=document.source_url,
                allowed_users=allowed_users,
                allowed_groups=allowed_groups,
                allowed_principals=allowed_principals,
                allowed_principal_labels=allowed_principal_labels,
            )
            return {
                "status": "indexed",
                "filename": document.filename,
                "source_url": document.source_url,
                "document_id": document.id,
                "connector_type": connector_type,
                "langflow_result": result,
            }
        else:
            # Create temporary file from document content
            import os

            from utils.file_utils import auto_cleanup_tempfile

            suffix = os.path.splitext(document.filename)[1]
            if not suffix:
                suffix = get_file_extension(document.mimetype)

            with auto_cleanup_tempfile(suffix=suffix) as tmp_path:
                # Write document content to temp file
                with open(tmp_path, "wb") as f:
                    f.write(document.content)

                logger.info(
                    "[CONNECTOR] Processing document",
                    document_id=document.id,
                    connector_type=connector_type,
                    filename=document.filename,
                )

                # Process using consolidated processing pipeline
                from models.processors import TaskProcessor

                processor = TaskProcessor(
                    document_service=self.document_service,
                    models_service=self.models_service,
                    docling_service=self.docling_service,
                )
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

                logger.info(
                    "[CONNECTOR] Document processed",
                    document_id=document.id,
                    status=result.get("status"),
                )

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
        id_field: str = "document_id",
    ):
        """Update indexed chunks with connector-specific metadata"""
        from utils.acl_utils import update_document_acl

        logger.debug("Looking for chunks", document_id=document.id)

        # Get user's OpenSearch client
        opensearch_client = self.session_manager.get_user_opensearch_client(
            owner_user_id, jwt_token
        )
        write_client = self.clients.opensearch
        if write_client is None:
            raise RuntimeError("Backend OpenSearch write client is unavailable")

        # Update ACL if changed (hash-based skip optimization).
        # Match both document_id and connector_file_id: non-Langflow connector
        # chunks store the connector id in connector_file_id (document_id holds the
        # content hash), while Langflow chunks store it in document_id.
        acl_result = await update_document_acl(
            document_id=document.id,
            acl=document.acl,
            opensearch_client=opensearch_client,
            write_opensearch_client=write_client,
            id_fields=("document_id", "connector_file_id"),
        )

        # Log ACL update result
        if acl_result["status"] == "unchanged":
            logger.debug(f"ACL unchanged for {document.id}, skipped update")
        elif acl_result["status"] == "updated":
            logger.info(
                f"Updated ACL for {document.id}, {acl_result['chunks_updated']} chunks updated"
            )
        elif acl_result["status"] == "error":
            logger.error(f"ACL update error for {document.id}: {acl_result.get('error')}")

        # Update other metadata fields (source_url, timestamps, etc.)
        # Use the backend client for writes; the scoped client above is only
        # used for DLS visibility/ACL-change checks.
        try:
            await write_client.update_by_query(
                index=self.index_name,
                body={
                    # Match both fields: non-Langflow chunks carry the connector id
                    # in connector_file_id (document_id is the content hash),
                    # Langflow chunks carry it in document_id.
                    "query": {
                        "bool": {
                            "should": [
                                {"term": {"document_id": document.id}},
                                {"term": {"connector_file_id": document.id}},
                            ],
                            "minimum_should_match": 1,
                        }
                    },
                    "script": {
                        "source": """
                            ctx._source.source_url = params.source_url;
                            ctx._source.connector_type = params.connector_type;
                            if (params.filename != null) {
                                ctx._source.filename = params.filename;
                            }
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
                            "filename": document.filename,
                            "created_time": document.created_time.isoformat()
                            if document.created_time
                            else None,
                            "modified_time": document.modified_time.isoformat()
                            if document.modified_time
                            else None,
                            "metadata": document.metadata,
                        },
                    },
                },
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
        replace_duplicates: bool = False,
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
        jwt_token = await self._get_effective_sync_jwt(user_id, jwt_token)

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
            raise ValueError(f"Connection '{connection_id}' not found or not authenticated")

        logger.debug("Got connector", authenticated=connector.is_authenticated)

        if not connector.is_authenticated:
            raise ValueError(f"Connection '{connection_id}' not authenticated")

        # Collect files to process (limited by max_files)
        files_to_process: list[dict[str, Any]] = []
        page_token = None

        # Calculate page size to minimize API calls
        page_size = min(max_files or 100, 1000) if max_files else 100

        while True:
            # List files from connector with limit
            logger.debug("Calling list_files", page_size=page_size, page_token=page_token)
            file_list = await connector.list_files(page_token, max_files=page_size)
            logger.debug("Got files from connector", file_count=len(file_list.get("files", [])))
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
            models_service=self.models_service,
            replace_duplicates=replace_duplicates,
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
        file_ids: list[str],
        jwt_token: str = None,
        file_infos: list[dict[str, Any]] = None,
        ingest_settings: dict[str, Any] | None = None,
        replace_duplicates: bool = False,
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
            ingest_settings: Optional UI-style dict (``embeddingModel``, ``chunkSize``, …) passed to
                ``ConnectorFileProcessor`` when Langflow ingest is disabled.
        """
        jwt_token = await self._get_effective_sync_jwt(user_id, jwt_token)

        if not self.task_service:
            raise ValueError(
                "TaskService not available - connector sync requires task service dependency"
            )

        connector = await self.get_connector(connection_id)
        if not connector:
            raise ValueError(f"Connection '{connection_id}' not found or not authenticated")

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
        if file_infos and hasattr(connector, "set_file_infos"):
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
        expanded_files_info = []

        try:
            # Set the file_ids we want to sync in the connector's config
            if hasattr(connector, "cfg"):
                connector.cfg.file_ids = file_ids
                connector.cfg.folder_ids = None

                # Get the expanded list of file IDs (folders will be expanded to their contents)
                # This uses the connector's list_files() which calls _iter_selected_items()
                result = await connector.list_files()
                expanded_files = result.get("files", [])
                expanded_file_ids = [f["id"] for f in expanded_files]

                # Save the expanded files info so we can set correct names in the task UI
                for f in expanded_files:
                    expanded_files_info.append(f)

                # Requested IDs that vanished during expansion are either
                # folders (replaced by their children) or gone at the source
                # (deleted/trashed). Re-add the non-folder ones so the
                # processor can run its deleted-at-source cleanup
                # (get_file_content -> 404 -> delete indexed chunks).
                expanded_set = set(expanded_file_ids)
                known_folder_ids = {
                    f["id"] for f in (file_infos or []) if f.get("isFolder") and f.get("id")
                }
                missing_ids = [
                    fid
                    for fid in file_ids
                    if fid not in expanded_set and fid not in known_folder_ids
                ]
                if missing_ids:
                    logger.info(
                        f"Re-adding {len(missing_ids)} file id(s) missing after expansion "
                        f"(possibly deleted at source)"
                    )
                    expanded_file_ids = expanded_file_ids + missing_ids

            if not expanded_file_ids:
                logger.warning(
                    f"No files found after expanding file_ids. "
                    f"Original IDs: {file_ids}. This may indicate all IDs were folders "
                    f"with no contents, or files that were filtered out."
                )
                # If we have file_infos with download URLs, use original file_ids
                # (OneDrive sharing IDs can't be expanded but can be downloaded directly)
                # Exclude folders — they have no downloadable content on their own.
                if file_infos:
                    non_folder_infos = [f for f in file_infos if not f.get("isFolder")]
                    non_folder_ids = [f["id"] for f in non_folder_infos if f.get("id")]
                    if non_folder_ids:
                        logger.info(
                            "Using original file IDs with cached download URLs (folders excluded)"
                        )
                        expanded_file_ids = non_folder_ids
                    else:
                        raise ValueError("No files to sync after expanding folders")
                else:
                    raise ValueError("No files to sync after expanding folders")

        except Exception as e:
            logger.error(f"Failed to expand file_ids via list_files(): {e}")
            # Preserve intentional validation failures (e.g., folders-only selection)
            if isinstance(e, ValueError):
                raise
            # Fallback path: still exclude known folders when metadata is available
            if file_infos:
                non_folder_ids = [
                    f["id"] for f in file_infos if f.get("id") and not f.get("isFolder")
                ]
                expanded_file_ids = non_folder_ids or file_ids
            else:
                expanded_file_ids = file_ids
        finally:
            # Restore original config values
            if hasattr(connector, "cfg"):
                connector.cfg.file_ids = original_file_ids
                connector.cfg.folder_ids = original_folder_ids

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
            models_service=self.models_service,
            ingest_settings=ingest_settings,
            replace_duplicates=replace_duplicates,
        )

        # Create custom task using TaskService
        original_filenames = {}

        # Combine file_infos and expanded_files_info
        all_infos = (file_infos or []) + expanded_files_info
        if all_infos:
            original_filenames = {
                f["id"]: clean_connector_filename(
                    f["name"], f.get("mimeType") or f.get("mimetype", "")
                )
                for f in all_infos
                if "id" in f and "name" in f
            }

        task_id = await self.task_service.create_custom_task(
            user_id, expanded_file_ids, processor, original_filenames=original_filenames
        )

        return task_id

    async def _get_connector(self, connection_id: str) -> BaseConnector | None:
        """Get a connector by connection ID (alias for get_connector)"""
        return await self.get_connector(connection_id)
