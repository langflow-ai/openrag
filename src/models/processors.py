from abc import ABC, abstractmethod
from typing import Any
from .tasks import UploadTask, FileTask
from utils.logging_config import get_logger

logger = get_logger(__name__)


class TaskProcessor(ABC):
    """Abstract base class for task processors"""

    @abstractmethod
    async def process_item(
        self, upload_task: UploadTask, item: Any, file_task: FileTask
    ) -> None:
        """
        Process a single item in the task.

        Args:
            upload_task: The overall upload task
            item: The item to process (could be file path, file info, etc.)
            file_task: The specific file task to update
        """
        pass


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
        self.document_service = document_service
        self.owner_user_id = owner_user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email

    async def process_item(
        self, upload_task: UploadTask, item: str, file_task: FileTask
    ) -> None:
        """Process a regular file path using DocumentService"""
        # This calls the existing logic with user context
        await self.document_service.process_single_file_task(
            upload_task,
            item,
            owner_user_id=self.owner_user_id,
            jwt_token=self.jwt_token,
            owner_name=self.owner_name,
            owner_email=self.owner_email,
        )


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
    ):
        self.connector_service = connector_service
        self.connection_id = connection_id
        self.files_to_process = files_to_process
        self.user_id = user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email
        # Create lookup map for file info - handle both file objects and file IDs
        self.file_info_map = {}
        for f in files_to_process:
            if isinstance(f, dict):
                # Full file info objects
                self.file_info_map[f["id"]] = f
            else:
                # Just file IDs - will need to fetch metadata during processing
                self.file_info_map[f] = None

    async def process_item(
        self, upload_task: UploadTask, item: str, file_task: FileTask
    ) -> None:
        """Process a connector file using ConnectorService"""
        from models.tasks import TaskStatus

        file_id = item  # item is the connector file ID
        self.file_info_map.get(file_id)

        # Get the connector and connection info
        connector = await self.connector_service.get_connector(self.connection_id)
        connection = await self.connector_service.connection_manager.get_connection(
            self.connection_id
        )
        if not connector or not connection:
            raise ValueError(f"Connection '{self.connection_id}' not found")

        # Get file content from connector (the connector will fetch metadata if needed)
        document = await connector.get_file_content(file_id)

        # Use the user_id passed during initialization
        if not self.user_id:
            raise ValueError("user_id not provided to ConnectorFileProcessor")

        # Process using existing pipeline
        result = await self.connector_service.process_connector_document(
            document,
            self.user_id,
            connection.connector_type,
            jwt_token=self.jwt_token,
            owner_name=self.owner_name,
            owner_email=self.owner_email,
        )

        file_task.status = TaskStatus.COMPLETED
        file_task.result = result
        upload_task.successful_files += 1


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
        self.langflow_connector_service = langflow_connector_service
        self.connection_id = connection_id
        self.files_to_process = files_to_process
        self.user_id = user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email
        # Create lookup map for file info - handle both file objects and file IDs
        self.file_info_map = {}
        for f in files_to_process:
            if isinstance(f, dict):
                # Full file info objects
                self.file_info_map[f["id"]] = f
            else:
                # Just file IDs - will need to fetch metadata during processing
                self.file_info_map[f] = None

    async def process_item(
        self, upload_task: UploadTask, item: str, file_task: FileTask
    ) -> None:
        """Process a connector file using LangflowConnectorService"""
        from models.tasks import TaskStatus

        file_id = item  # item is the connector file ID
        self.file_info_map.get(file_id)

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

        # Get file content from connector (the connector will fetch metadata if needed)
        document = await connector.get_file_content(file_id)

        # Use the user_id passed during initialization
        if not self.user_id:
            raise ValueError("user_id not provided to LangflowConnectorFileProcessor")

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
        upload_task.successful_files += 1


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

        self.document_service = document_service
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
        from config.settings import INDEX_NAME, EMBED_MODEL, clients
        from services.document_service import chunk_texts_for_embeddings
        from utils.document_processing import process_document_sync

        file_task.status = TaskStatus.RUNNING
        file_task.updated_at = time.time()

        tmp = tempfile.NamedTemporaryFile(delete=False)
        try:
            # Download object to temporary file
            self.s3_client.download_fileobj(self.bucket, item, tmp)
            tmp.flush()

            loop = asyncio.get_event_loop()
            slim_doc = await loop.run_in_executor(
                self.document_service.process_pool, process_document_sync, tmp.name
            )

            opensearch_client = (
                self.document_service.session_manager.get_user_opensearch_client(
                    self.owner_user_id, self.jwt_token
                )
            )
            exists = await opensearch_client.exists(index=INDEX_NAME, id=slim_doc["id"])
            if exists:
                result = {"status": "unchanged", "id": slim_doc["id"]}
            else:
                texts = [c["text"] for c in slim_doc["chunks"]]
                text_batches = chunk_texts_for_embeddings(texts, max_tokens=8000)
                embeddings = []
                for batch in text_batches:
                    resp = await clients.patched_async_client.embeddings.create(
                        model=EMBED_MODEL, input=batch
                    )
                    embeddings.extend([d.embedding for d in resp.data])

                # Get object size
                try:
                    obj_info = self.s3_client.head_object(Bucket=self.bucket, Key=item)
                    file_size = obj_info.get("ContentLength", 0)
                except Exception:
                    file_size = 0

                for i, (chunk, vect) in enumerate(zip(slim_doc["chunks"], embeddings)):
                    chunk_doc = {
                        "document_id": slim_doc["id"],
                        "filename": slim_doc["filename"],
                        "mimetype": slim_doc["mimetype"],
                        "page": chunk["page"],
                        "text": chunk["text"],
                        "chunk_embedding": vect,
                        "file_size": file_size,
                        "connector_type": "s3",  # S3 uploads
                        "indexed_time": datetime.datetime.now().isoformat(),
                    }

                    # Only set owner fields if owner_user_id is provided (for no-auth mode support)
                    if self.owner_user_id is not None:
                        chunk_doc["owner"] = self.owner_user_id
                    if self.owner_name is not None:
                        chunk_doc["owner_name"] = self.owner_name
                    if self.owner_email is not None:
                        chunk_doc["owner_email"] = self.owner_email
                    chunk_id = f"{slim_doc['id']}_{i}"
                    try:
                        await opensearch_client.index(
                            index=INDEX_NAME, id=chunk_id, body=chunk_doc
                        )
                    except Exception as e:
                        logger.error(
                            "OpenSearch indexing failed for S3 chunk",
                            chunk_id=chunk_id,
                            error=str(e),
                            chunk_doc=chunk_doc,
                        )
                        raise

                result = {"status": "indexed", "id": slim_doc["id"]}

            result["path"] = f"s3://{self.bucket}/{item}"
            file_task.status = TaskStatus.COMPLETED
            file_task.result = result
            upload_task.successful_files += 1

        except Exception as e:
            file_task.status = TaskStatus.FAILED
            file_task.error = str(e)
            upload_task.failed_files += 1
        finally:
            tmp.close()
            os.remove(tmp.name)
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
    ):
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
            # Read file content
            with open(item, 'rb') as f:
                content = f.read()

            # Create file tuple for upload
            temp_filename = os.path.basename(item)
            # Extract original filename from temp file suffix (remove tmp prefix)
            if "_" in temp_filename:
                filename = temp_filename.split("_", 1)[1]  # Get everything after first _
            else:
                filename = temp_filename
            content_type, _ = mimetypes.guess_type(filename)
            if not content_type:
                content_type = 'application/octet-stream'
            
            file_tuple = (filename, content, content_type)

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