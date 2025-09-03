import os
import asyncio
import shutil
from pathlib import Path
from config.settings import DATA_DIRECTORY, clients, INDEX_NAME

FIRST_RUN_MARKER = ".openrag_initialized"

async def is_first_run():
    """Check if this is the first run by looking for initialization marker"""
    marker_path = Path(FIRST_RUN_MARKER)
    return not marker_path.exists()

async def mark_initialized():
    """Create marker file to indicate successful initialization"""
    marker_path = Path(FIRST_RUN_MARKER)
    marker_path.write_text("initialized")

async def has_existing_documents():
    """Check if there are already documents in the OpenSearch index"""
    try:
        response = await clients.opensearch.search(
            index=INDEX_NAME,
            body={"size": 0, "track_total_hits": True}
        )
        total_docs = response["hits"]["total"]["value"]
        return total_docs > 0
    except Exception as e:
        print(f"Error checking existing documents: {e}")
        return False

async def copy_external_files_to_documents():
    """Copy files from DATA_DIRECTORY to documents folder if they're different locations"""
    data_dir = Path(DATA_DIRECTORY)
    documents_dir = Path("./documents")
    
    # Create documents directory if it doesn't exist
    documents_dir.mkdir(exist_ok=True)
    
    # If DATA_DIRECTORY is the same as documents, no need to copy
    if data_dir.resolve() == documents_dir.resolve():
        print(f"[FIRST_RUN] DATA_DIRECTORY ({DATA_DIRECTORY}) is the same as documents folder, no copying needed")
        return []
    
    if not data_dir.exists() or not data_dir.is_dir():
        print(f"[FIRST_RUN] External dataset directory {DATA_DIRECTORY} does not exist or is not a directory")
        return []
    
    print(f"[FIRST_RUN] Copying files from {DATA_DIRECTORY} to documents folder...")
    
    copied_files = []
    supported_extensions = ['.pdf', '.txt', '.doc', '.docx', '.md', '.rtf', '.odt']
    
    # Get all files recursively from the external directory
    for file_path in data_dir.rglob("*"):
        if file_path.is_file() and not file_path.name.startswith("."):
            # Filter for document types
            if file_path.suffix.lower() in supported_extensions:
                # Create relative path to maintain directory structure
                relative_path = file_path.relative_to(data_dir)
                dest_path = documents_dir / relative_path
                
                # Create destination directory if it doesn't exist
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Only copy if file doesn't exist or is different
                if not dest_path.exists() or file_path.stat().st_mtime > dest_path.stat().st_mtime:
                    try:
                        shutil.copy2(file_path, dest_path)
                        copied_files.append(str(dest_path.absolute()))
                        print(f"[FIRST_RUN] Copied: {file_path} -> {dest_path}")
                    except Exception as e:
                        print(f"[FIRST_RUN] Failed to copy {file_path}: {e}")
                else:
                    # File already exists and is up to date, but include it in the list
                    copied_files.append(str(dest_path.absolute()))
    
    print(f"[FIRST_RUN] Copied {len(copied_files)} files to documents folder")
    return copied_files

async def get_default_dataset_files():
    """Get list of files in the documents directory (after copying if needed)"""
    documents_dir = Path("./documents")
    
    if not documents_dir.exists() or not documents_dir.is_dir():
        print(f"[FIRST_RUN] Documents directory does not exist")
        return []
    
    # Get all files recursively, excluding hidden files and directories
    files = []
    supported_extensions = ['.pdf', '.txt', '.doc', '.docx', '.md', '.rtf', '.odt']
    
    for file_path in documents_dir.rglob("*"):
        if file_path.is_file() and not file_path.name.startswith("."):
            # Filter for document types
            if file_path.suffix.lower() in supported_extensions:
                files.append(str(file_path.absolute()))
    
    return files

def should_run_initialization():
    """Determine if we should run first-run initialization"""
    # Check for environment variable to skip initialization
    skip_init = os.getenv("SKIP_FIRST_RUN_INIT", "false").lower() in ["true", "1", "yes"]
    if skip_init:
        return False
    
    return True