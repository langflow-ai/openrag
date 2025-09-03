import os
from pathlib import Path
from config.settings import is_no_auth_mode
from utils.first_run import has_existing_documents, is_first_run, mark_initialized, should_run_initialization, copy_external_files_to_documents
from services.task_service import TaskService


def create_system_user_context():
    """Create appropriate system user context for first-run operations"""
    from session_manager import User
    
    # Create user context for task tracking (not for document ownership)
    system_user = User(
        user_id="anonymous" if is_no_auth_mode() else "global",
        email="anonymous@localhost" if is_no_auth_mode() else "system@openrag.local",
        name="Anonymous User" if is_no_auth_mode() else "Default Dataset"
    )
    jwt_token = None
    
    return system_user, jwt_token


async def run_first_time_setup(task_service: TaskService) -> bool:
    """Run first-time setup if needed using existing upload workflow"""
    try:
        if not should_run_initialization():
            print("[FIRST_RUN] Initialization skipped due to SKIP_FIRST_RUN_INIT")
            return True
        
        first_run = await is_first_run()
        existing_docs = await has_existing_documents()
        
        # Only ingest if it's first run AND there are no existing documents
        should_ingest = first_run and not existing_docs
        print(f"[FIRST_RUN] First run: {first_run}, Existing docs: {existing_docs}, Should ingest: {should_ingest}")
        
        if not should_ingest:
            print("[FIRST_RUN] Skipping first-time setup")
            return True
        
        # Copy external files to documents folder if needed
        copied_files = await copy_external_files_to_documents()
        if copied_files:
            print(f"[FIRST_RUN] Successfully copied {len(copied_files)} files from external directory")
        
        # Get documents directory
        documents_dir = Path("./documents")
        if not documents_dir.exists() or not documents_dir.is_dir():
            print("[FIRST_RUN] Documents directory does not exist")
            await mark_initialized()
            return True
        
        # Get all supported files (same logic as upload_path)
        file_paths = []
        supported_extensions = ['.pdf', '.txt', '.doc', '.docx', '.md', '.rtf', '.odt']
        
        for root, _, files in os.walk(documents_dir):
            for fn in files:
                if not fn.startswith("."):  # Skip hidden files
                    file_path = Path(root) / fn
                    if file_path.suffix.lower() in supported_extensions:
                        file_paths.append(str(file_path))
        
        if not file_paths:
            print("[FIRST_RUN] No supported files found in documents directory")
            await mark_initialized()
            return True
        
        print(f"[FIRST_RUN] Found {len(file_paths)} files to ingest from documents directory")
        
        # Create system user context
        system_user, jwt_token = create_system_user_context()
        
        # Use existing create_upload_task - same as upload_path API
        if is_no_auth_mode():
            # In no-auth mode, use anonymous user as normal
            task_id = await task_service.create_upload_task(
                user_id=system_user.user_id,
                file_paths=file_paths,
                jwt_token=jwt_token,
                owner_name=system_user.name,
                owner_email=system_user.email
            )
        else:
            # In auth mode, we need to create a custom processor that passes None for owner_user_id
            # This creates documents without owner field, making them globally accessible
            from models.processors import DocumentFileProcessor
            processor = DocumentFileProcessor(
                task_service.document_service,
                owner_user_id=None,  # This is the key - no owner means globally accessible
                jwt_token=jwt_token,
                owner_name=None,  # No name either
                owner_email=None   # No email either
            )
            task_id = await task_service.create_custom_task("global", file_paths, processor)
        
        print(f"[FIRST_RUN] Created upload task {task_id} for default dataset ingestion")
        
        # Mark as initialized - the task will continue in background
        await mark_initialized()
        print("[FIRST_RUN] Default dataset ingestion initiated successfully")
        return True
        
    except Exception as e:
        print(f"[FIRST_RUN] Error during first-time setup: {e}")
        # Still mark as initialized to prevent retrying on every startup
        await mark_initialized()
        return False