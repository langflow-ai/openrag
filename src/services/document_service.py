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

from config.settings import clients, INDEX_NAME, EMBED_MODEL
from utils.document_processing import extract_relevant, process_document_sync


def get_token_count(text: str, model: str = EMBED_MODEL) -> int:
    """Get accurate token count using tiktoken"""
    try:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except KeyError:
        # Fallback to cl100k_base for unknown models
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))


def chunk_texts_for_embeddings(
    texts: List[str], max_tokens: int = None, model: str = EMBED_MODEL
) -> List[List[str]]:
    """
    Split texts into batches that won't exceed token limits.
    If max_tokens is None, returns texts as single batch (no splitting).
    """
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

    async def process_file_common(
        self,
        file_path: str,
        file_hash: str = None,
        owner_user_id: str = None,
        original_filename: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        file_size: int = None,
        connector_type: str = "local",
    ):
        """
        Common processing logic for both upload and upload_path.
        1. Optionally compute SHA256 hash if not provided.
        2. Convert with docling and extract relevant content.
        3. Add embeddings.
        4. Index into OpenSearch.
        """
        if file_hash is None:
            sha256 = hashlib.sha256()
            async with aiofiles.open(file_path, "rb") as f:
                while True:
                    chunk = await f.read(1 << 20)
                    if not chunk:
                        break
                    sha256.update(chunk)
            file_hash = sha256.hexdigest()

        # Get user's OpenSearch client with JWT for OIDC auth
        opensearch_client = self.session_manager.get_user_opensearch_client(
            owner_user_id, jwt_token
        )

        exists = await opensearch_client.exists(index=INDEX_NAME, id=file_hash)
        if exists:
            return {"status": "unchanged", "id": file_hash}

        # convert and extract
        result = clients.converter.convert(file_path)
        full_doc = result.document.export_to_dict()
        slim_doc = extract_relevant(full_doc)

        texts = [c["text"] for c in slim_doc["chunks"]]

        # Split into batches to avoid token limits (8191 limit, use 8000 with buffer)
        text_batches = chunk_texts_for_embeddings(texts, max_tokens=8000)
        embeddings = []

        for batch in text_batches:
            resp = await clients.patched_async_client.embeddings.create(
                model=EMBED_MODEL, input=batch
            )
            embeddings.extend([d.embedding for d in resp.data])

        # Index each chunk as a separate document
        for i, (chunk, vect) in enumerate(zip(slim_doc["chunks"], embeddings)):
            chunk_doc = {
                "document_id": file_hash,
                "filename": original_filename
                if original_filename
                else slim_doc["filename"],
                "mimetype": slim_doc["mimetype"],
                "page": chunk["page"],
                "text": chunk["text"],
                "chunk_embedding": vect,
                "file_size": file_size,
                "connector_type": connector_type,
                "indexed_time": datetime.datetime.now().isoformat(),
            }

            # Only set owner fields if owner_user_id is provided (for no-auth mode support)
            if owner_user_id is not None:
                chunk_doc["owner"] = owner_user_id
            if owner_name is not None:
                chunk_doc["owner_name"] = owner_name
            if owner_email is not None:
                chunk_doc["owner_email"] = owner_email
            chunk_id = f"{file_hash}_{i}"
            try:
                await opensearch_client.index(
                    index=INDEX_NAME, id=chunk_id, body=chunk_doc
                )
            except Exception as e:
                logger.error(
                    "OpenSearch indexing failed for chunk",
                    chunk_id=chunk_id,
                    error=str(e),
                )
                logger.error("Chunk document details", chunk_doc=chunk_doc)
                raise
        return {"status": "indexed", "id": file_hash}

    async def process_upload_file(
        self,
        upload_file,
        owner_user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
    ):
        """Process an uploaded file from form data"""
        sha256 = hashlib.sha256()
        tmp = tempfile.NamedTemporaryFile(delete=False)
        file_size = 0
        try:
            while True:
                chunk = await upload_file.read(1 << 20)
                if not chunk:
                    break
                sha256.update(chunk)
                tmp.write(chunk)
                file_size += len(chunk)
            tmp.flush()

            file_hash = sha256.hexdigest()
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

            result = await self.process_file_common(
                tmp.name,
                file_hash,
                owner_user_id=owner_user_id,
                original_filename=upload_file.filename,
                jwt_token=jwt_token,
                owner_name=owner_name,
                owner_email=owner_email,
                file_size=file_size,
            )
            return result

        finally:
            tmp.close()
            os.remove(tmp.name)

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

    async def process_single_file_task(
        self,
        upload_task,
        file_path: str,
        owner_user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        connector_type: str = "local",
    ):
        """Process a single file and update task tracking - used by task service"""
        from models.tasks import TaskStatus
        import time
        import asyncio

        file_task = upload_task.file_tasks[file_path]
        file_task.status = TaskStatus.RUNNING
        file_task.updated_at = time.time()

        try:
            # Handle regular file processing
            loop = asyncio.get_event_loop()

            # Run CPU-intensive docling processing in separate process
            slim_doc = await loop.run_in_executor(
                self.process_pool, process_document_sync, file_path
            )

            # Check if already indexed
            opensearch_client = self.session_manager.get_user_opensearch_client(
                owner_user_id, jwt_token
            )
            exists = await opensearch_client.exists(index=INDEX_NAME, id=slim_doc["id"])
            if exists:
                result = {"status": "unchanged", "id": slim_doc["id"]}
            else:
                # Generate embeddings and index (I/O bound, keep in main process)
                texts = [c["text"] for c in slim_doc["chunks"]]

                # Split into batches to avoid token limits (8191 limit, use 8000 with buffer)
                text_batches = chunk_texts_for_embeddings(texts, max_tokens=8000)
                embeddings = []

                for batch in text_batches:
                    resp = await clients.patched_async_client.embeddings.create(
                        model=EMBED_MODEL, input=batch
                    )
                    embeddings.extend([d.embedding for d in resp.data])

                # Get file size
                file_size = 0
                try:
                    file_size = os.path.getsize(file_path)
                except OSError:
                    pass  # Keep file_size as 0 if can't get size

                # Index each chunk
                for i, (chunk, vect) in enumerate(zip(slim_doc["chunks"], embeddings)):
                    chunk_doc = {
                        "document_id": slim_doc["id"],
                        "filename": slim_doc["filename"],
                        "mimetype": slim_doc["mimetype"],
                        "page": chunk["page"],
                        "text": chunk["text"],
                        "chunk_embedding": vect,
                        "file_size": file_size,
                        "connector_type": connector_type,
                        "indexed_time": datetime.datetime.now().isoformat(),
                    }

                    # Only set owner fields if owner_user_id is provided (for no-auth mode support)
                    if owner_user_id is not None:
                        chunk_doc["owner"] = owner_user_id
                    if owner_name is not None:
                        chunk_doc["owner_name"] = owner_name
                    if owner_email is not None:
                        chunk_doc["owner_email"] = owner_email
                    chunk_id = f"{slim_doc['id']}_{i}"
                    try:
                        await opensearch_client.index(
                            index=INDEX_NAME, id=chunk_id, body=chunk_doc
                        )
                    except Exception as e:
                        logger.error(
                            "OpenSearch indexing failed for batch chunk",
                            chunk_id=chunk_id,
                            error=str(e),
                        )
                        logger.error("Chunk document details", chunk_doc=chunk_doc)
                        raise

                result = {"status": "indexed", "id": slim_doc["id"]}

            result["path"] = file_path
            file_task.status = TaskStatus.COMPLETED
            file_task.result = result
            upload_task.successful_files += 1

        except Exception as e:
            import traceback
            from concurrent.futures import BrokenExecutor

            if isinstance(e, BrokenExecutor):
                logger.error(
                    "Process pool broken while processing file", file_path=file_path
                )
                logger.info("Worker process likely crashed")
                logger.info(
                    "You should see detailed crash logs above from the worker process"
                )

                # Mark pool as broken for potential recreation
                self._process_pool_broken = True

                # Attempt to recreate the pool for future operations
                if self._recreate_process_pool():
                    logger.info("Process pool successfully recreated")
                else:
                    logger.warning(
                        "Failed to recreate process pool - future operations may fail"
                    )

                file_task.error = f"Worker process crashed: {str(e)}"
            else:
                logger.error(
                    "Failed to process file", file_path=file_path, error=str(e)
                )
                file_task.error = str(e)

            logger.error("Full traceback available")
            traceback.print_exc()
            file_task.status = TaskStatus.FAILED
            upload_task.failed_files += 1
        finally:
            file_task.updated_at = time.time()
            upload_task.processed_files += 1
            upload_task.updated_at = time.time()

            if upload_task.processed_files >= upload_task.total_files:
                upload_task.status = TaskStatus.COMPLETED
