import datetime
import hashlib
import tempfile
import os
import aiofiles
from io import BytesIO
from docling_core.types.io import DocumentStream
from typing import List
import openai
import tiktoken
from utils.logging_config import get_logger

logger = get_logger(__name__)

from config.settings import clients, INDEX_NAME, get_embedding_model
from utils.document_processing import extract_relevant, process_document_sync


def get_token_count(text: str, model: str = None) -> int:
    """Get accurate token count using tiktoken"""
    model = model or get_embedding_model()
    try:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except KeyError:
        # Fallback to cl100k_base for unknown models
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))


def chunk_texts_for_embeddings(
    texts: List[str], max_tokens: int = None, model: str = None
) -> List[List[str]]:
    """
    Split texts into batches that won't exceed token limits.
    If max_tokens is None, returns texts as single batch (no splitting).
    """
    model = model or get_embedding_model()

    if max_tokens is None:
        return [texts]

    batches = []
    current_batch = []
    current_tokens = 0

    for text in texts:
        text_tokens = get_token_count(text, model)

        # If single text exceeds limit, split it further
        if text_tokens > max_tokens:
            # If we have current batch, save it first
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0

            # Split the large text into smaller chunks
            try:
                encoding = tiktoken.encoding_for_model(model)
            except KeyError:
                encoding = tiktoken.get_encoding("cl100k_base")

            tokens = encoding.encode(text)

            for i in range(0, len(tokens), max_tokens):
                chunk_tokens = tokens[i : i + max_tokens]
                chunk_text = encoding.decode(chunk_tokens)
                batches.append([chunk_text])

        # If adding this text would exceed limit, start new batch
        elif current_tokens + text_tokens > max_tokens:
            if current_batch:  # Don't add empty batches
                batches.append(current_batch)
            current_batch = [text]
            current_tokens = text_tokens

        # Add to current batch
        else:
            current_batch.append(text)
            current_tokens += text_tokens

    # Add final batch if not empty
    if current_batch:
        batches.append(current_batch)

    return batches


class DocumentService:
    def __init__(self, process_pool=None, session_manager=None):
        self.process_pool = process_pool
        self.session_manager = session_manager
        self._mapping_ensured = False
        self._process_pool_broken = False

    def _recreate_process_pool(self):
        """Recreate the process pool if it's broken"""
        if self._process_pool_broken and self.process_pool:
            logger.warning("Attempting to recreate broken process pool")
            try:
                # Shutdown the old pool
                self.process_pool.shutdown(wait=False)

                # Import and create a new pool
                from utils.process_pool import MAX_WORKERS
                from concurrent.futures import ProcessPoolExecutor

                self.process_pool = ProcessPoolExecutor(max_workers=MAX_WORKERS)
                self._process_pool_broken = False
                logger.info("Process pool recreated", worker_count=MAX_WORKERS)
                return True
            except Exception as e:
                logger.error("Failed to recreate process pool", error=str(e))
                return False
        return False


    async def process_upload_file(
        self,
        upload_file,
        owner_user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
    ):
        """Process an uploaded file from form data"""
        from utils.hash_utils import hash_id
        from utils.file_utils import auto_cleanup_tempfile
        import os

        # Preserve file extension for docling format detection
        filename = upload_file.filename or "uploaded"
        suffix = os.path.splitext(filename)[1] or ""

        with auto_cleanup_tempfile(suffix=suffix) as tmp_path:
            # Stream upload file to temporary file
            file_size = 0
            with open(tmp_path, 'wb') as tmp_file:
                while True:
                    chunk = await upload_file.read(1 << 20)
                    if not chunk:
                        break
                    tmp_file.write(chunk)
                    file_size += len(chunk)

            file_hash = hash_id(tmp_path)
            # Get user's OpenSearch client with JWT for OIDC auth
            opensearch_client = self.session_manager.get_user_opensearch_client(
                owner_user_id, jwt_token
            )

            try:
                exists = await opensearch_client.exists(index=INDEX_NAME, id=file_hash)
            except Exception as e:
                logger.error(
                    "OpenSearch exists check failed", file_hash=file_hash, error=str(e)
                )
                raise
            if exists:
                return {"status": "unchanged", "id": file_hash}

            # Use consolidated standard processing
            from models.processors import TaskProcessor
            processor = TaskProcessor(document_service=self)
            result = await processor.process_document_standard(
                file_path=tmp_path,
                file_hash=file_hash,
                owner_user_id=owner_user_id,
                original_filename=upload_file.filename,
                jwt_token=jwt_token,
                owner_name=owner_name,
                owner_email=owner_email,
                file_size=file_size,
                connector_type="local",
            )
            return result

    async def process_upload_context(self, upload_file, filename: str = None):
        """Process uploaded file and return content for context"""
        import io

        if not filename:
            filename = upload_file.filename or "uploaded_document"

        # Stream file content into BytesIO
        content = io.BytesIO()
        while True:
            chunk = await upload_file.read(1 << 20)  # 1MB chunks
            if not chunk:
                break
            content.write(chunk)
        content.seek(0)  # Reset to beginning for reading

        # Create DocumentStream and process with docling
        doc_stream = DocumentStream(name=filename, stream=content)
        result = clients.converter.convert(doc_stream)
        full_doc = result.document.export_to_dict()
        slim_doc = extract_relevant(full_doc)

        # Extract all text content
        all_text = []
        for chunk in slim_doc["chunks"]:
            all_text.append(f"Page {chunk['page']}:\n{chunk['text']}")

        full_content = "\n\n".join(all_text)

        return {
            "filename": filename,
            "content": full_content,
            "pages": len(slim_doc["chunks"]),
            "content_length": len(full_content),
        }
