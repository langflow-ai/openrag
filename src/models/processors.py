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
    
    def __init__(self, connector_service, connection_id: str, files_to_process: list, user_id: str = None):
        self.connector_service = connector_service
        self.connection_id = connection_id
        self.files_to_process = files_to_process
        self.user_id = user_id
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
        
        # Get the connector
        connector = await self.connector_service.get_connector(self.connection_id)
        if not connector:
            raise ValueError(f"Connection '{self.connection_id}' not found")
        
        # Get file content from connector (the connector will fetch metadata if needed)
        document = await connector.get_file_content(file_id)
        
        # Use the user_id passed during initialization
        if not self.user_id:
            raise ValueError("user_id not provided to ConnectorFileProcessor")
        
        # Process using existing pipeline
        result = await self.connector_service.process_connector_document(document, self.user_id)
        
        file_task.status = TaskStatus.COMPLETED
        file_task.result = result
        upload_task.successful_files += 1