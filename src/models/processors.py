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
    
    def __init__(self, document_service):
        self.document_service = document_service
    
    async def process_item(self, upload_task: UploadTask, item: str, file_task: FileTask) -> None:
        """Process a regular file path using DocumentService"""
        # This calls the existing logic
        await self.document_service.process_single_file_task(upload_task, item)


class ConnectorFileProcessor(TaskProcessor):
    """Processor for connector file uploads"""
    
    def __init__(self, connector_service, connection_id: str, files_to_process: list):
        self.connector_service = connector_service
        self.connection_id = connection_id
        self.files_to_process = files_to_process
        # Create lookup map for file info
        self.file_info_map = {f['id']: f for f in files_to_process}
    
    async def process_item(self, upload_task: UploadTask, item: str, file_task: FileTask) -> None:
        """Process a connector file using ConnectorService"""
        from models.tasks import TaskStatus
        import time
        
        file_id = item  # item is the connector file ID
        file_info = self.file_info_map.get(file_id)
        
        if not file_info:
            raise ValueError(f"File info not found for {file_id}")
        
        # Get the connector
        connector = await self.connector_service.get_connector(self.connection_id)
        if not connector:
            raise ValueError(f"Connection '{self.connection_id}' not found")
        
        # Get file content from connector
        document = await connector.get_file_content(file_info['id'])
        
        # Get user_id from task store lookup
        user_id = None
        for uid, tasks in self.connector_service.task_service.task_store.items():
            if upload_task.task_id in tasks:
                user_id = uid
                break
        
        if not user_id:
            raise ValueError("Could not determine user_id for task")
        
        # Process using existing pipeline
        result = await self.connector_service.process_connector_document(document, user_id)
        
        file_task.status = TaskStatus.COMPLETED
        file_task.result = result
        upload_task.successful_files += 1