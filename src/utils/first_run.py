import os
import asyncio
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

async def get_default_dataset_files():
    """Get list of files in the default dataset directory"""
    data_dir = Path(DATA_DIRECTORY)
    if not data_dir.exists() or not data_dir.is_dir():
        print(f"Default dataset directory {DATA_DIRECTORY} does not exist or is not a directory")
        return []
    
    # Get all files recursively, excluding hidden files and directories
    files = []
    for file_path in data_dir.rglob("*"):
        if file_path.is_file() and not file_path.name.startswith("."):
            # Filter for document types (pdf, txt, doc, docx, etc.)
            if file_path.suffix.lower() in ['.pdf', '.txt', '.doc', '.docx', '.md', '.rtf', '.odt']:
                files.append(str(file_path.absolute()))
    
    return files

def should_run_initialization():
    """Determine if we should run first-run initialization"""
    # Check for environment variable to skip initialization
    skip_init = os.getenv("SKIP_FIRST_RUN_INIT", "false").lower() in ["true", "1", "yes"]
    if skip_init:
        return False
    
    return True