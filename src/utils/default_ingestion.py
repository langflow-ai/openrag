import asyncio
import os
from pathlib import Path
from typing import List
from utils.first_run import get_default_dataset_files, has_existing_documents, is_first_run, mark_initialized, should_run_initialization
from services.task_service import TaskService
from services.document_service import DocumentService

class DefaultDatasetIngestor:
    """Handles automatic ingestion of default datasets on first run"""
    
    def __init__(self, document_service: DocumentService, task_service: TaskService):
        self.document_service = document_service
        self.task_service = task_service
    
    async def should_ingest(self) -> bool:
        """Check if we should perform default dataset ingestion"""
        if not should_run_initialization():
            print("[FIRST_RUN] Initialization skipped due to SKIP_FIRST_RUN_INIT")
            return False
        
        first_run = await is_first_run()
        existing_docs = await has_existing_documents()
        
        # Only ingest if it's first run AND there are no existing documents
        should_ingest = first_run and not existing_docs
        
        print(f"[FIRST_RUN] First run: {first_run}, Existing docs: {existing_docs}, Should ingest: {should_ingest}")
        return should_ingest
    
    async def ingest_default_dataset(self) -> bool:
        """Ingest the default dataset files"""
        try:
            files = await get_default_dataset_files()
            
            if not files:
                print("[FIRST_RUN] No default dataset files found to ingest")
                await mark_initialized()
                return True
            
            print(f"[FIRST_RUN] Found {len(files)} files to ingest from default dataset")
            
            # Create a system task for ingesting default files
            # Use a dummy user ID for system operations
            system_user_id = "system"
            task_id = await self.task_service.create_upload_task(
                user_id=system_user_id,
                file_paths=files,
                jwt_token=None,  # No JWT needed for system operations
                owner_name="System",
                owner_email="system@openrag.local"
            )
            
            print(f"[FIRST_RUN] Created task {task_id} for default dataset ingestion")
            
            # Wait a bit for the task to start processing
            await asyncio.sleep(2)
            
            # Monitor task progress (but don't block indefinitely)
            max_wait_time = 300  # 5 minutes max
            check_interval = 5  # Check every 5 seconds
            elapsed_time = 0
            
            while elapsed_time < max_wait_time:
                try:
                    task_status = await self.task_service.get_task_status(task_id)
                    if task_status and task_status.get("status") in ["completed", "failed"]:
                        break
                    
                    await asyncio.sleep(check_interval)
                    elapsed_time += check_interval
                    
                    # Log progress every 30 seconds
                    if elapsed_time % 30 == 0:
                        processed = task_status.get("processed", 0) if task_status else 0
                        total = len(files)
                        print(f"[FIRST_RUN] Task {task_id} progress: {processed}/{total} files processed")
                
                except Exception as e:
                    print(f"[FIRST_RUN] Error checking task status: {e}")
                    break
            
            # Mark as initialized regardless of task completion
            # The task will continue running in the background if needed
            await mark_initialized()
            print("[FIRST_RUN] Default dataset ingestion initiated successfully")
            return True
            
        except Exception as e:
            print(f"[FIRST_RUN] Error during default dataset ingestion: {e}")
            # Still mark as initialized to prevent retrying on every startup
            await mark_initialized()
            return False

async def run_first_time_setup(document_service: DocumentService, task_service: TaskService) -> bool:
    """Run first-time setup if needed"""
    ingestor = DefaultDatasetIngestor(document_service, task_service)
    
    if await ingestor.should_ingest():
        print("[FIRST_RUN] Starting first-time default dataset ingestion...")
        return await ingestor.ingest_default_dataset()
    else:
        print("[FIRST_RUN] Skipping first-time setup")
        return True