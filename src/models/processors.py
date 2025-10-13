from typing import Any
from .tasks import UploadTask, FileTask
from utils.logging_config import get_logger

logger = get_logger(__name__)


class TaskProcessor:
    """Base class for task processors with shared processing logic"""

    def __init__(self, document_service=None):
        self.document_service = document_service

    async def check_document_exists(
        self,
        file_hash: str,
        opensearch_client,
    ) -> bool:
        """
        Check if a document with the given hash already exists in OpenSearch.
        Consolidated hash checking for all processors.
        """
        from config.settings import INDEX_NAME
        import asyncio

        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                exists = await opensearch_client.exists(index=INDEX_NAME, id=file_hash)
                return exists
            except (asyncio.TimeoutError, Exception) as e:
                if attempt == max_retries - 1:
                    logger.error(
                        "OpenSearch exists check failed after retries",
                        file_hash=file_hash,
                        error=str(e),
                        attempt=attempt + 1
                    )
                    # On final failure, assume document doesn't exist (safer to reprocess than skip)
                    logger.warning(
                        "Assuming document doesn't exist due to connection issues",
                        file_hash=file_hash
                    )
                    return False
                else:
                    logger.warning(
                        "OpenSearch exists check failed, retrying",
                        file_hash=file_hash,
                        error=str(e),
                        attempt=attempt + 1,
                        retry_in=retry_delay
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff

    async def check_filename_exists(
        self,
        filename: str,
        opensearch_client,
    ) -> bool:
        """
        Check if a document with the given filename already exists in OpenSearch.
        Returns True if any chunks with this filename exist.
        """
        from config.settings import INDEX_NAME
        from utils.opensearch_queries import build_filename_search_body
        import asyncio

        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                # Search for any document with this exact filename
                search_body = build_filename_search_body(filename, size=1, source=False)

                response = await opensearch_client.search(
                    index=INDEX_NAME,
                    body=search_body
                )

                # Check if any hits were found
                hits = response.get("hits", {}).get("hits", [])
                return len(hits) > 0

            except (asyncio.TimeoutError, Exception) as e:
                if attempt == max_retries - 1:
                    logger.error(
                        "OpenSearch filename check failed after retries",
                        filename=filename,
                        error=str(e),
                        attempt=attempt + 1
                    )
                    # On final failure, assume document doesn't exist (safer to reprocess than skip)
                    logger.warning(
                        "Assuming filename doesn't exist due to connection issues",
                        filename=filename
                    )
                    return False
                else:
                    logger.warning(
                        "OpenSearch filename check failed, retrying",
                        filename=filename,
                        error=str(e),
                        attempt=attempt + 1,
                        retry_in=retry_delay
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff

    async def delete_document_by_filename(
        self,
        filename: str,
        opensearch_client,
    ) -> None:
        """
        Delete all chunks of a document with the given filename from OpenSearch.
        """
        from config.settings import INDEX_NAME
        from utils.opensearch_queries import build_filename_delete_body

        try:
            # Delete all documents with this filename
            delete_body = build_filename_delete_body(filename)

            response = await opensearch_client.delete_by_query(
                index=INDEX_NAME,
                body=delete_body
            )

            deleted_count = response.get("deleted", 0)
            logger.info(
                "Deleted existing document chunks",
                filename=filename,
                deleted_count=deleted_count
            )

        except Exception as e:
            logger.error(
                "Failed to delete existing document",
                filename=filename,
                error=str(e)
            )
            raise

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
    ):
        """
        Standard processing pipeline for non-Langflow processors:
        docling conversion + embeddings + OpenSearch indexing.

        Args:
            embedding_model: Embedding model to use (defaults to the current
                embedding model from settings)
        """
        import datetime
        from config.settings import INDEX_NAME, clients, get_embedding_model
        from services.document_service import chunk_texts_for_embeddings
        from utils.document_processing import extract_relevant
        from utils.embedding_fields import get_embedding_field_name, ensure_embedding_field_exists

        # Use provided embedding model or fall back to default
        embedding_model = embedding_model or get_embedding_model()

        # Get user's OpenSearch client with JWT for OIDC auth
        opensearch_client = self.document_service.session_manager.get_user_opensearch_client(
            owner_user_id, jwt_token
        )

        # Check if already exists
        if await self.check_document_exists(file_hash, opensearch_client):
            return {"status": "unchanged", "id": file_hash}

        # Ensure the embedding field exists for this model
        embedding_field_name = await ensure_embedding_field_exists(
            opensearch_client, embedding_model, INDEX_NAME
        )

        logger.info(
            "Processing document with embedding model",
            embedding_model=embedding_model,
            embedding_field=embedding_field_name,
            file_hash=file_hash,
        )

        # Convert and extract
        result = clients.converter.convert(file_path)
        full_doc = result.document.export_to_dict()
        slim_doc = extract_relevant(full_doc)

        texts = [c["text"] for c in slim_doc["chunks"]]

        # Split into batches to avoid token limits (8191 limit, use 8000 with buffer)
        text_batches = chunk_texts_for_embeddings(texts, max_tokens=8000)
        embeddings = []

        for batch in text_batches:
            resp = await clients.patched_async_client.embeddings.create(
                model=embedding_model, input=batch
            )
            embeddings.extend([d.embedding for d in resp.data])

        # Index each chunk as a separate document
        for i, (chunk, vect) in enumerate(zip(slim_doc["chunks"], embeddings)):
            chunk_doc = {
                "document_id": file_hash,
                "filename": original_filename
                if original_filename
                else slim_doc["filename"],
                "mimetype": slim_doc["mimetype"],
                "page": chunk["page"],
                "text": chunk["text"],
                # Store embedding in model-specific field
                embedding_field_name: vect,
                # Track which model was used
                "embedding_model": embedding_model,
                "embedding_dimensions": len(vect),
                "file_size": file_size,
                "connector_type": connector_type,
                "indexed_time": datetime.datetime.now().isoformat(),
            }

            # Only set owner fields if owner_user_id is provided (for no-auth mode support)
            if owner_user_id is not None:
                chunk_doc["owner"] = owner_user_id
            if owner_name is not None:
                chunk_doc["owner_name"] = owner_name
            if owner_email is not None:
                chunk_doc["owner_email"] = owner_email
            chunk_id = f"{file_hash}_{i}"
            try:
                await opensearch_client.index(
                    index=INDEX_NAME, id=chunk_id, body=chunk_doc
                )
            except Exception as e:
                logger.error(
                    "OpenSearch indexing failed for chunk",
                    chunk_id=chunk_id,
                    error=str(e),
                )
                logger.error("Chunk document details", chunk_doc=chunk_doc)
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
        owner_user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
    ):
        super().__init__(document_service)
        self.owner_user_id = owner_user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email

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
                connector_type="local",
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
    ):
        super().__init__(document_service=document_service)
        self.connector_service = connector_service
        self.connection_id = connection_id
        self.files_to_process = files_to_process
        self.user_id = user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email

    async def process_item(
        self, upload_task: UploadTask, item: str, file_task: FileTask
    ) -> None:
        """Process a connector file using consolidated methods"""
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
            connector = await self.connector_service.get_connector(self.connection_id)
            connection = await self.connector_service.connection_manager.get_connection(
                self.connection_id
            )
            if not connector or not connection:
                raise ValueError(f"Connection '{self.connection_id}' not found")

            # Get file content from connector
            document = await connector.get_file_content(file_id)

            if not self.user_id:
                raise ValueError("user_id not provided to ConnectorFileProcessor")

            # Create temporary file from document content
            from utils.file_utils import auto_cleanup_tempfile

            suffix = self.connector_service._get_file_extension(document.mimetype)
            with auto_cleanup_tempfile(suffix=suffix) as tmp_path:
                # Write content to temp file
                with open(tmp_path, 'wb') as f:
                    f.write(document.content)

                # Compute hash
                file_hash = hash_id(tmp_path)

                # Use consolidated standard processing
                result = await self.process_document_standard(
                    file_path=tmp_path,
                    file_hash=file_hash,
                    owner_user_id=self.user_id,
                    original_filename=document.filename,
                    jwt_token=self.jwt_token,
                    owner_name=self.owner_name,
                    owner_email=self.owner_email,
                    file_size=len(document.content),
                    connector_type=connection.connector_type,
                )

                # Add connector-specific metadata
                result.update({
                    "source_url": document.source_url,
                    "document_id": document.id,
                })

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
    ):
        super().__init__()
        self.langflow_connector_service = langflow_connector_service
        self.connection_id = connection_id
        self.files_to_process = files_to_process
        self.user_id = user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email

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

            if not self.user_id:
                raise ValueError("user_id not provided to LangflowConnectorFileProcessor")

            # Create temporary file and compute hash to check for duplicates
            from utils.file_utils import auto_cleanup_tempfile

            suffix = self.langflow_connector_service._get_file_extension(document.mimetype)
            with auto_cleanup_tempfile(suffix=suffix) as tmp_path:
                # Write content to temp file
                with open(tmp_path, 'wb') as f:
                    f.write(document.content)

                # Compute hash and check if already exists
                file_hash = hash_id(tmp_path)

                # Check if document already exists
                opensearch_client = self.langflow_connector_service.session_manager.get_user_opensearch_client(
                    self.user_id, self.jwt_token
                )
                if await self.check_document_exists(file_hash, opensearch_client):
                    file_task.status = TaskStatus.COMPLETED
                    file_task.result = {"status": "unchanged", "id": file_hash}
                    file_task.updated_at = time.time()
                    upload_task.successful_files += 1
                    return

                # Process using Langflow pipeline
                result = await self.langflow_connector_service.process_connector_document(
                    document,
                    self.user_id,
                    connection.connector_type,
                    jwt_token=self.jwt_token,
                    owner_name=self.owner_name,
                    owner_email=self.owner_email,
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
    ):
        import boto3

        super().__init__(document_service)
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
        from config.settings import INDEX_NAME, clients, get_embedding_model
        from services.document_service import chunk_texts_for_embeddings
        from utils.document_processing import process_document_sync

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

            # Check if document with same filename already exists
            opensearch_client = self.session_manager.get_user_opensearch_client(
                self.owner_user_id, self.jwt_token
            )

            filename_exists = await self.check_filename_exists(original_filename, opensearch_client)

            if filename_exists and not self.replace_duplicates:
                # Duplicate exists and user hasn't confirmed replacement
                file_task.status = TaskStatus.FAILED
                file_task.error = f"File with name '{original_filename}' already exists"
                file_task.updated_at = time.time()
                upload_task.failed_files += 1
                return
            elif filename_exists and self.replace_duplicates:
                # Delete existing document before uploading new one
                logger.info(f"Replacing existing document: {original_filename}")
                await self.delete_document_by_filename(original_filename, opensearch_client)

            # Read file content for processing
            with open(item, 'rb') as f:
                content = f.read()

            # Create file tuple for upload using ORIGINAL filename
            # This ensures the document is indexed with the original name
            content_type, _ = mimetypes.guess_type(original_filename)
            if not content_type:
                content_type = 'application/octet-stream'

            file_tuple = (original_filename, content, content_type)

            # Get JWT token using same logic as DocumentFileProcessor
            # This will handle anonymous JWT creation if needed
            effective_jwt = self.jwt_token
            if self.session_manager and not effective_jwt:
                # Let session manager handle anonymous JWT creation if needed
                self.session_manager.get_user_opensearch_client(
                    self.owner_user_id, self.jwt_token
                )
                # The session manager would have created anonymous JWT if needed
                # Get it from the session manager's internal state
                if hasattr(self.session_manager, '_anonymous_jwt'):
                    effective_jwt = self.session_manager._anonymous_jwt

            # Prepare metadata tweaks similar to API endpoint
            final_tweaks = self.tweaks.copy() if self.tweaks else {}
            
            metadata_tweaks = []
            if self.owner_user_id:
                metadata_tweaks.append({"key": "owner", "value": self.owner_user_id})
            if self.owner_name:
                metadata_tweaks.append({"key": "owner_name", "value": self.owner_name})
            if self.owner_email:
                metadata_tweaks.append({"key": "owner_email", "value": self.owner_email})
            # Mark as local upload for connector_type
            metadata_tweaks.append({"key": "connector_type", "value": "local"})

            if metadata_tweaks:
                # Initialize the OpenSearch component tweaks if not already present
                if "OpenSearchHybrid-Ve6bS" not in final_tweaks:
                    final_tweaks["OpenSearchHybrid-Ve6bS"] = {}
                final_tweaks["OpenSearchHybrid-Ve6bS"]["docs_metadata"] = metadata_tweaks

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
                connector_type="local",

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
