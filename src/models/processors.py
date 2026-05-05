from typing import Any, Dict, Optional
from .tasks import UploadTask, FileTask
from utils.logging_config import get_logger
from utils.file_utils import (
    get_file_extension,
    clean_connector_filename,
)

logger = get_logger(__name__)


class TaskProcessor:
    """Base class for task processors with shared processing logic"""

    def __init__(self, document_service=None, models_service=None):
        self.document_service = document_service
        self.models_service = models_service

    async def process_document_standard(
        self,
        file_path: str,
        file_hash: str,
        owner_user_id: str = None,
        original_filename: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        file_size: int = None,
        connector_type: str = "local",
        embedding_model: str = None,
        chunk_size: int = None,
        chunk_overlap: int = None,
        is_sample_data: bool = False,
        acl: "DocumentACL" = None,
        extra_metadata: dict[str, Any] | None = None,
    ):
        """
        Standard processing pipeline for non-Langflow processors:
        docling conversion + embeddings + active knowledge-backend indexing.

        Args:
            embedding_model: Embedding model to use (defaults to the current
                embedding model from settings)
            chunk_size: Optional character window size for re-splitting extracted
                chunks (non-Langflow path, e.g. connector UI ``chunkSize``).
            chunk_overlap: Overlap between windows; must be less than ``chunk_size``.
            acl: DocumentACL instance with access control information
        """
        import datetime
        from config.settings import clients, get_embedding_model, get_openrag_config
        from services.document_service import chunk_texts_for_embeddings
        from services.knowledge_access import build_access_context
        from services.knowledge_backend import get_knowledge_backend_service
        from utils.document_processing import (
            extract_relevant,
            resplit_chunks_character_windows,
        )

        # Use provided embedding model or configured model.
        # get_embedding_model() returns empty string when Langflow ingest is enabled,
        # but OpenRAG processors still need a concrete embedding model.
        configured_embedding_model = get_openrag_config().knowledge.embedding_model
        embedding_model = (
            embedding_model
            or configured_embedding_model
            or get_embedding_model()
        )

        access_context = build_access_context(
            user_id=owner_user_id,
            user_email=owner_email,
            jwt_token=jwt_token,
            session_manager=self.document_service.session_manager,
        )
        knowledge_backend = get_knowledge_backend_service(
            self.document_service.session_manager
        )

        # Check if already exists
        if await knowledge_backend.document_exists(file_hash, access_context):
            return {"status": "unchanged", "id": file_hash}

        logger.info(
            "Processing document with embedding model",
            embedding_model=embedding_model,
            file_hash=file_hash,
        )

        # Check if this is a .txt or .md file - use simple processing instead of docling
        import os
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext in ('.txt', '.md'):
            # Simple text file processing without docling
            from utils.document_processing import process_text_file
            logger.info(
                "Processing as plain text file (bypassing docling)",
                file_path=file_path,
                file_hash=file_hash,
            )
            slim_doc = process_text_file(file_path)
            # Override filename with original_filename if provided
            if original_filename:
                slim_doc["filename"] = original_filename
        else:
            from utils.docling_client import convert_file

            full_doc = await convert_file(file_path, httpx_client=clients.docling_http_client)
            slim_doc = extract_relevant(full_doc)

        if chunk_size is not None:
            try:
                cs = int(chunk_size)
            except (TypeError, ValueError):
                cs = 0
            if cs > 0:
                try:
                    co = (
                        int(chunk_overlap)
                        if chunk_overlap is not None
                        else 0
                    )
                except (TypeError, ValueError):
                    co = 0
                if co < cs:
                    slim_doc["chunks"] = resplit_chunks_character_windows(
                        slim_doc["chunks"], cs, max(0, co)
                    )

        texts = [c["text"] for c in slim_doc["chunks"]]

        litellm_embedding_model = await self.models_service.get_litellm_model_name(embedding_model) if self.models_service is not None else embedding_model

        # Split into batches to avoid token limits (8191 limit, use 8000 with buffer or 2000 if it's ollama)
        if "ollama" in litellm_embedding_model:
            text_batches = chunk_texts_for_embeddings(texts, max_tokens=2000)
        else:
            text_batches = chunk_texts_for_embeddings(texts, max_tokens=8000)
        embeddings = []

        for batch in text_batches:
            resp = await clients.patched_embedding_client.embeddings.create(
                model=litellm_embedding_model, input=batch
            )
            embeddings.extend([d["embedding"] if isinstance(d, dict) else d.embedding for d in resp.data])

        if not embeddings or len(embeddings) == 0:
            logger.error(
                "No embeddings generated — document may be empty or unreadable",
                file_hash=file_hash,
                embedding_model=embedding_model,
            )
            return {"status": "error", "error": "No text content could be extracted from document"}

        normalized_chunks = []
        for i, (chunk, vect) in enumerate(zip(slim_doc["chunks"], embeddings)):
            chunk_metadata = {
                "document_id": file_hash,
                "filename": original_filename
                if original_filename
                else slim_doc["filename"],
                "mimetype": slim_doc["mimetype"],
                "page": chunk["page"],
                "embedding_model": embedding_model,
                "embedding_dimensions": len(vect),
                "file_size": file_size,
                "connector_type": connector_type,
                "indexed_time": datetime.datetime.now().isoformat(),
            }

            # Set owner and ACL fields
            if acl:
                # Use ACL data if provided (from connector)
                chunk_metadata["owner"] = acl.owner if acl.owner else owner_user_id
                chunk_metadata["allowed_users"] = acl.allowed_users
                chunk_metadata["allowed_groups"] = acl.allowed_groups
            else:
                # Fallback to owner_user_id if no ACL (local uploads)
                if owner_user_id is not None:
                    chunk_metadata["owner"] = owner_user_id
                    chunk_metadata["allowed_users"] = []
                    chunk_metadata["allowed_groups"] = []

            # Set owner metadata fields (for display)
            if owner_name is not None:
                chunk_metadata["owner_name"] = owner_name
            if owner_email is not None:
                chunk_metadata["owner_email"] = owner_email

            # Mark as sample data if specified
            if is_sample_data:
                chunk_metadata["is_sample_data"] = "true"
            if extra_metadata:
                chunk_metadata.update(extra_metadata)

            normalized_chunks.append(
                {
                    "id": f"{file_hash}_{i}",
                    "text": chunk["text"],
                    "embedding": vect,
                    "embedding_model": embedding_model,
                    "metadata": chunk_metadata,
                }
            )

        try:
            await knowledge_backend.index_chunks(normalized_chunks, access_context)
        except Exception as e:
            logger.error(
                "Knowledge backend indexing failed",
                file_hash=file_hash,
                error=str(e),
            )
            logger.error("Chunk document details", chunks=normalized_chunks)
            raise
        return {"status": "indexed", "id": file_hash}

    async def process_item(
        self, upload_task: UploadTask, item: Any, file_task: FileTask
    ) -> None:
        """
        Process a single item in the task.

        This is a base implementation that should be overridden by subclasses.
        When TaskProcessor is used directly (not via subclass), this method
        is not called - only the utility methods like process_document_standard
        are used.

        Args:
            upload_task: The overall upload task
            item: The item to process (could be file path, file info, etc.)
            file_task: The specific file task to update
        """
        raise NotImplementedError(
            "process_item should be overridden by subclasses when used in task processing"
        )


class DocumentFileProcessor(TaskProcessor):
    """Default processor for regular file uploads"""

    def __init__(
        self,
        document_service,
        models_service,
        owner_user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        is_sample_data: bool = False,
        connector_type: str = "local",
    ):
        super().__init__(document_service, models_service)
        self.owner_user_id = owner_user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email
        self.is_sample_data = is_sample_data
        self.connector_type = connector_type

    async def process_item(
        self, upload_task: UploadTask, item: str, file_task: FileTask
    ) -> None:
        """Process a regular file path using consolidated methods"""
        from models.tasks import TaskStatus
        from utils.hash_utils import hash_id
        import time
        import os

        file_task.status = TaskStatus.RUNNING
        file_task.updated_at = time.time()

        try:
            # Compute hash
            file_hash = hash_id(item)

            # Get file size
            try:
                file_size = os.path.getsize(item)
            except Exception:
                file_size = 0

            # Use consolidated standard processing
            result = await self.process_document_standard(
                file_path=item,
                file_hash=file_hash,
                owner_user_id=self.owner_user_id,
                original_filename=os.path.basename(item),
                jwt_token=self.jwt_token,
                owner_name=self.owner_name,
                owner_email=self.owner_email,
                file_size=file_size,
                connector_type=self.connector_type,
                is_sample_data=self.is_sample_data,
            )

            file_task.status = TaskStatus.COMPLETED
            file_task.result = result
            file_task.updated_at = time.time()
            upload_task.successful_files += 1

        except Exception as e:
            file_task.status = TaskStatus.FAILED
            file_task.error = str(e)
            file_task.updated_at = time.time()
            upload_task.failed_files += 1
            raise
        finally:
            upload_task.processed_files += 1
            upload_task.updated_at = time.time()


class ConnectorFileProcessor(TaskProcessor):
    """Processor for connector file uploads"""

    def __init__(
        self,
        connector_service,
        connection_id: str,
        files_to_process: list,
        user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        document_service=None,
        models_service=None,
        ingest_settings: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(document_service=document_service, models_service=models_service)
        self.connector_service = connector_service
        self.connection_id = connection_id
        self.files_to_process = files_to_process
        self.user_id = user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email
        self.ingest_settings = ingest_settings

    async def process_item(
        self, upload_task: UploadTask, item: str, file_task: FileTask
    ) -> None:
        """Process a connector file using consolidated methods"""
        from models.tasks import TaskStatus
        import time

        file_task.status = TaskStatus.RUNNING
        file_task.updated_at = time.time()

        try:
            file_id = item  # item is the connector file ID

            # Get the connector and connection info
            connector = await self.connector_service.get_connector(self.connection_id)
            connection = await self.connector_service.connection_manager.get_connection(
                self.connection_id
            )
            if not connector or not connection:
                raise ValueError(f"Connection '{self.connection_id}' not found")

            # Get file content from connector
            document = await connector.get_file_content(file_id)
            
            # Update filename in task once we have it from the connector
            file_task.filename = clean_connector_filename(document.filename, document.mimetype)

            if not self.user_id:
                raise ValueError("user_id not provided to ConnectorFileProcessor")

            result = await self.connector_service.process_connector_document(
                document,
                self.user_id,
                connection.connector_type,
                jwt_token=self.jwt_token,
                owner_name=self.owner_name,
                owner_email=self.owner_email,
                ingest_settings=self.ingest_settings,
            )

            file_task.status = TaskStatus.COMPLETED
            file_task.result = result
            file_task.updated_at = time.time()
            upload_task.successful_files += 1

        except Exception as e:
            file_task.status = TaskStatus.FAILED
            file_task.error = str(e)
            file_task.updated_at = time.time()
            upload_task.failed_files += 1
            raise


class LangflowConnectorFileProcessor(TaskProcessor):
    """Processor for connector file uploads using Langflow"""

    def __init__(
        self,
        langflow_connector_service,
        connection_id: str,
        files_to_process: list,
        user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        ingest_settings: Optional[Dict[str, Any]] = None,
    ):
        super().__init__()
        self.langflow_connector_service = langflow_connector_service
        self.connection_id = connection_id
        self.files_to_process = files_to_process
        self.user_id = user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email
        self.ingest_settings = ingest_settings

    async def process_item(
        self, upload_task: UploadTask, item: str, file_task: FileTask
    ) -> None:
        """Process a connector file using LangflowConnectorService"""
        from models.tasks import TaskStatus
        from utils.hash_utils import hash_id
        import tempfile
        import time
        import os

        file_task.status = TaskStatus.RUNNING
        file_task.updated_at = time.time()

        try:
            file_id = item  # item is the connector file ID

            # Get the connector and connection info
            connector = await self.langflow_connector_service.get_connector(
                self.connection_id
            )
            connection = (
                await self.langflow_connector_service.connection_manager.get_connection(
                    self.connection_id
                )
            )
            if not connector or not connection:
                raise ValueError(f"Connection '{self.connection_id}' not found")

            # Get file content from connector
            document = await connector.get_file_content(file_id)

            # Update filename in task once we have it from the connector
            file_task.filename = clean_connector_filename(document.filename, document.mimetype)

            if not self.user_id:
                raise ValueError("user_id not provided to LangflowConnectorFileProcessor")

            # Create a temporary file for connector ingestion.
            from utils.file_utils import auto_cleanup_tempfile

            suffix = get_file_extension(document.mimetype)
            with auto_cleanup_tempfile(suffix=suffix) as tmp_path:
                # Write content to temp file
                with open(tmp_path, 'wb') as f:
                    f.write(document.content)

                # Process using Langflow pipeline
                result = await self.langflow_connector_service.process_connector_document(
                    document,
                    self.user_id,
                    connection.connector_type,
                    jwt_token=self.jwt_token,
                    owner_name=self.owner_name,
                    owner_email=self.owner_email,
                    ingest_settings=self.ingest_settings,
                )

            file_task.status = TaskStatus.COMPLETED
            file_task.result = result
            file_task.updated_at = time.time()
            upload_task.successful_files += 1

        except Exception as e:
            file_task.status = TaskStatus.FAILED
            file_task.error = str(e)
            file_task.updated_at = time.time()
            upload_task.failed_files += 1
            raise


class S3FileProcessor(TaskProcessor):
    """Processor for files stored in S3 buckets"""

    def __init__(
        self,
        document_service,
        bucket: str,
        s3_client=None,
        owner_user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        models_service=None,
    ):
        import boto3

        super().__init__(document_service, models_service)
        self.bucket = bucket
        self.s3_client = s3_client or boto3.client("s3")
        self.owner_user_id = owner_user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email

    async def process_item(
        self, upload_task: UploadTask, item: str, file_task: FileTask
    ) -> None:
        """Download an S3 object and process it using DocumentService"""
        from models.tasks import TaskStatus
        import tempfile
        import os
        import time
        import asyncio
        import datetime
        from config.settings import clients, get_embedding_model, get_index_name
        file_task.status = TaskStatus.RUNNING
        file_task.updated_at = time.time()

        from utils.file_utils import auto_cleanup_tempfile
        from utils.hash_utils import hash_id

        try:
            with auto_cleanup_tempfile() as tmp_path:
                # Download object to temporary file
                with open(tmp_path, 'wb') as tmp_file:
                    self.s3_client.download_fileobj(self.bucket, item, tmp_file)

                # Compute hash
                file_hash = hash_id(tmp_path)

                # Get object size
                try:
                    obj_info = self.s3_client.head_object(Bucket=self.bucket, Key=item)
                    file_size = obj_info.get("ContentLength", 0)
                except Exception:
                    file_size = 0

                # Use consolidated standard processing
                result = await self.process_document_standard(
                    file_path=tmp_path,
                    file_hash=file_hash,
                    owner_user_id=self.owner_user_id,
                    original_filename=item,  # Use S3 key as filename
                    jwt_token=self.jwt_token,
                    owner_name=self.owner_name,
                    owner_email=self.owner_email,
                    file_size=file_size,
                    connector_type="s3",
                )

                result["path"] = f"s3://{self.bucket}/{item}"
                file_task.status = TaskStatus.COMPLETED
                file_task.result = result
                upload_task.successful_files += 1

        except Exception as e:
            file_task.status = TaskStatus.FAILED
            file_task.error = str(e)
            upload_task.failed_files += 1
        finally:
            file_task.updated_at = time.time()


class LangflowFileProcessor(TaskProcessor):
    """Processor for Langflow file uploads with upload and ingest"""

    def __init__(
        self,
        langflow_file_service,
        session_manager,
        owner_user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        session_id: str = None,
        tweaks: dict = None,
        settings: dict = None,
        delete_after_ingest: bool = True,
        replace_duplicates: bool = False,
        connector_type: str = "local",
    ):
        super().__init__()
        self.langflow_file_service = langflow_file_service
        self.session_manager = session_manager
        self.owner_user_id = owner_user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email
        self.session_id = session_id
        self.tweaks = tweaks or {}
        self.settings = settings
        self.delete_after_ingest = delete_after_ingest
        self.replace_duplicates = replace_duplicates
        self.connector_type = connector_type

    async def process_item(
        self, upload_task: UploadTask, item: str, file_task: FileTask
    ) -> None:
        """Process a file path using LangflowFileService upload_and_ingest_file"""
        import mimetypes
        import os
        from models.tasks import TaskStatus
        import time

        # Update task status
        file_task.status = TaskStatus.RUNNING
        file_task.updated_at = time.time()

        try:
            # Use the ORIGINAL filename stored in file_task (not the transformed temp path)
            # This ensures we check/store the original filename with spaces, etc.
            original_filename = file_task.filename or os.path.basename(item)

            from services.knowledge_access import build_access_context
            from services.knowledge_backend import get_knowledge_backend_service

            access_context = build_access_context(
                user_id=self.owner_user_id,
                user_email=self.owner_email,
                jwt_token=self.jwt_token,
                session_manager=self.session_manager,
            )
            knowledge_backend = get_knowledge_backend_service(self.session_manager)
            filename_exists = await knowledge_backend.filename_exists(
                original_filename,
                access_context,
            )

            if filename_exists and not self.replace_duplicates:
                file_task.status = TaskStatus.FAILED
                file_task.error = f"File with name '{original_filename}' already exists"
                file_task.updated_at = time.time()
                upload_task.failed_files += 1
                return
            if filename_exists and self.replace_duplicates:
                logger.info(f"Replacing existing document: {original_filename}")
                await knowledge_backend.delete_by_filename(
                    original_filename,
                    access_context,
                )

            # Read file content for processing
            with open(item, 'rb') as f:
                content = f.read()

            # Create file tuple for upload using ORIGINAL filename
            # This ensures the document is indexed with the original name
            content_type, _ = mimetypes.guess_type(original_filename)
            if not content_type:
                content_type = 'application/octet-stream'

            # Rename .txt to .md for Langflow compatibility
            # Langflow has issues processing text/plain files
            langflow_filename = original_filename
            if original_filename.lower().endswith('.txt'):
                langflow_filename = original_filename[:-4] + '.md'
                content_type = 'text/markdown'
                logger.debug(f"Renamed {original_filename} to {langflow_filename} for Langflow")

            file_tuple = (langflow_filename, content, content_type)

            # Get JWT token using same logic as DocumentFileProcessor
            # This will handle anonymous JWT creation if needed
            effective_jwt = self.jwt_token
            if self.session_manager and not effective_jwt:
                effective_jwt = self.session_manager.get_effective_jwt_token(
                    self.owner_user_id,
                    self.jwt_token,
                )

            # Prepare metadata tweaks similar to API endpoint
            final_tweaks = self.tweaks.copy() if self.tweaks else {}

            # Process file using langflow service
            result = await self.langflow_file_service.upload_and_ingest_file(
                file_tuple=file_tuple,
                session_id=self.session_id,
                tweaks=final_tweaks,
                settings=self.settings,
                jwt_token=effective_jwt,
                delete_after_ingest=self.delete_after_ingest,
                owner=self.owner_user_id,
                owner_name=self.owner_name,
                owner_email=self.owner_email,
                connector_type=self.connector_type,
            )

            # Update task with success
            file_task.status = TaskStatus.COMPLETED
            file_task.result = result
            file_task.updated_at = time.time()
            upload_task.successful_files += 1

        except Exception as e:
            # Update task with failure
            file_task.status = TaskStatus.FAILED
            file_task.error_message = str(e)
            file_task.updated_at = time.time()
            upload_task.failed_files += 1
            raise


from .url import LangflowUrlProcessor
