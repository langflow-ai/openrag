import asyncio
import uuid
import time
import random
from typing import Dict
from concurrent.futures import ProcessPoolExecutor

from models.tasks import TaskStatus, UploadTask, FileTask
from utils.gpu_detection import get_worker_count

class TaskService:
    def __init__(self, document_service=None):
        self.document_service = document_service
        self.task_store: Dict[str, Dict[str, UploadTask]] = {}  # user_id -> {task_id -> UploadTask}
        self.background_tasks = set()
        
        # Initialize process pool
        max_workers = get_worker_count()
        self.process_pool = ProcessPoolExecutor(max_workers=max_workers)
        print(f"Process pool initialized with {max_workers} workers")

    async def exponential_backoff_delay(self, retry_count: int, base_delay: float = 1.0, max_delay: float = 60.0) -> None:
        """Apply exponential backoff with jitter"""
        delay = min(base_delay * (2 ** retry_count) + random.uniform(0, 1), max_delay)
        await asyncio.sleep(delay)

    async def create_upload_task(self, user_id: str, file_paths: list) -> str:
        """Create a new upload task for bulk file processing"""
        task_id = str(uuid.uuid4())
        upload_task = UploadTask(
            task_id=task_id,
            total_files=len(file_paths),
            file_tasks={path: FileTask(file_path=path) for path in file_paths}
        )
        
        if user_id not in self.task_store:
            self.task_store[user_id] = {}
        self.task_store[user_id][task_id] = upload_task
        
        # Start background processing
        background_task = asyncio.create_task(self.background_upload_processor(user_id, task_id))
        self.background_tasks.add(background_task)
        background_task.add_done_callback(self.background_tasks.discard)
        
        return task_id

    async def background_upload_processor(self, user_id: str, task_id: str) -> None:
        """Background task to process all files in an upload job with concurrency control"""
        try:
            upload_task = self.task_store[user_id][task_id]
            upload_task.status = TaskStatus.RUNNING
            upload_task.updated_at = time.time()
            
            # Process files with limited concurrency to avoid overwhelming the system
            max_workers = get_worker_count()
            semaphore = asyncio.Semaphore(max_workers * 2)  # Allow 2x process pool size for async I/O
            
            async def process_with_semaphore(file_path: str):
                async with semaphore:
                    await self.document_service.process_single_file_task(upload_task, file_path)
            
            tasks = [
                process_with_semaphore(file_path)
                for file_path in upload_task.file_tasks.keys()
            ]
            
            await asyncio.gather(*tasks, return_exceptions=True)
            
        except Exception as e:
            print(f"[ERROR] Background upload processor failed for task {task_id}: {e}")
            import traceback
            traceback.print_exc()
            if user_id in self.task_store and task_id in self.task_store[user_id]:
                self.task_store[user_id][task_id].status = TaskStatus.FAILED
                self.task_store[user_id][task_id].updated_at = time.time()

    def get_task_status(self, user_id: str, task_id: str) -> dict:
        """Get the status of a specific upload task"""
        if (not task_id or 
            user_id not in self.task_store or 
            task_id not in self.task_store[user_id]):
            return None
        
        upload_task = self.task_store[user_id][task_id]
        
        file_statuses = {}
        for file_path, file_task in upload_task.file_tasks.items():
            file_statuses[file_path] = {
                "status": file_task.status.value,
                "result": file_task.result,
                "error": file_task.error,
                "retry_count": file_task.retry_count,
                "created_at": file_task.created_at,
                "updated_at": file_task.updated_at
            }
        
        return {
            "task_id": upload_task.task_id,
            "status": upload_task.status.value,
            "total_files": upload_task.total_files,
            "processed_files": upload_task.processed_files,
            "successful_files": upload_task.successful_files,
            "failed_files": upload_task.failed_files,
            "created_at": upload_task.created_at,
            "updated_at": upload_task.updated_at,
            "files": file_statuses
        }
    
    def shutdown(self):
        """Cleanup process pool"""
        if hasattr(self, 'process_pool'):
            self.process_pool.shutdown(wait=True)