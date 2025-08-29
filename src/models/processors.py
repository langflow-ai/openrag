from abc import ABC, abstractmethod
from typing import Any, Dict
from .tasks import UploadTask, FileTask


class TaskProcessor(ABC):
    """Abstract base class for task processors"""
    
    @abstractmethod
    async def process_item(self, upload_task: UploadTask, item: Any, file_task: FileTask) -> None:
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
    
    def __init__(self, document_service, owner_user_id: str = None, jwt_token: str = None, owner_name: str = None, owner_email: str = None):
        self.document_service = document_service
        self.owner_user_id = owner_user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email
    
    async def process_item(self, upload_task: UploadTask, item: str, file_task: FileTask) -> None:
        """Process a regular file path using DocumentService"""
        # This calls the existing logic with user context
        await self.document_service.process_single_file_task(
            upload_task, item, 
            owner_user_id=self.owner_user_id, 
            jwt_token=self.jwt_token,
            owner_name=self.owner_name,
            owner_email=self.owner_email
        )


class ConnectorFileProcessor(TaskProcessor):
    """Processor for connector file uploads"""
    
    def __init__(self, connector_service, connection_id: str, files_to_process: list, user_id: str = None, jwt_token: str = None, owner_name: str = None, owner_email: str = None):
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
                self.file_info_map[f['id']] = f
            else:
                # Just file IDs - will need to fetch metadata during processing
                self.file_info_map[f] = None
    
    async def process_item(self, upload_task: UploadTask, item: str, file_task: FileTask) -> None:
        """Process a connector file using ConnectorService"""
        from models.tasks import TaskStatus
        import time
        
        file_id = item  # item is the connector file ID
        file_info = self.file_info_map.get(file_id)
        
        # Get the connector and connection info
        connector = await self.connector_service.get_connector(self.connection_id)
        connection = await self.connector_service.connection_manager.get_connection(self.connection_id)
        if not connector or not connection:
            raise ValueError(f"Connection '{self.connection_id}' not found")
        
        # Get file content from connector (the connector will fetch metadata if needed)
        document = await connector.get_file_content(file_id)
        
        # Use the user_id passed during initialization
        if not self.user_id:
            raise ValueError("user_id not provided to ConnectorFileProcessor")
        
        # Process using existing pipeline
        result = await self.connector_service.process_connector_document(document, self.user_id, connection.connector_type, jwt_token=self.jwt_token, owner_name=self.owner_name, owner_email=self.owner_email)
        
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

    async def process_item(self, upload_task: UploadTask, item: str, file_task: FileTask) -> None:
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

            opensearch_client = self.document_service.session_manager.get_user_opensearch_client(
                self.owner_user_id, self.jwt_token
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
                    file_size = obj_info.get('ContentLength', 0)
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
                        "owner": self.owner_user_id,
                        "owner_name": self.owner_name,
                        "owner_email": self.owner_email,
                        "file_size": file_size,
                        "connector_type": "s3",  # S3 uploads
                        "indexed_time": datetime.datetime.now().isoformat(),
                    }
                    chunk_id = f"{slim_doc['id']}_{i}"
                    try:
                        await opensearch_client.index(index=INDEX_NAME, id=chunk_id, body=chunk_doc)
                    except Exception as e:
                        print(f"[ERROR] OpenSearch indexing failed for S3 chunk {chunk_id}: {e}")
                        print(f"[ERROR] Chunk document: {chunk_doc}")
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
