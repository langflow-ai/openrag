import datetime
import hashlib
import tempfile
import os
import aiofiles
from io import BytesIO
from docling_core.types.io import DocumentStream

from config.settings import clients, INDEX_NAME, EMBED_MODEL
from utils.document_processing import extract_relevant, process_document_sync

class DocumentService:
    def __init__(self, process_pool=None):
        self.process_pool = process_pool
    
    async def process_file_common(self, file_path: str, file_hash: str = None, owner_user_id: str = None):
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

        exists = await clients.opensearch.exists(index=INDEX_NAME, id=file_hash)
        if exists:
            return {"status": "unchanged", "id": file_hash}

        # convert and extract
        result = clients.converter.convert(file_path)
        full_doc = result.document.export_to_dict()
        slim_doc = extract_relevant(full_doc)

        texts = [c["text"] for c in slim_doc["chunks"]]
        resp = await clients.patched_async_client.embeddings.create(model=EMBED_MODEL, input=texts)
        embeddings = [d.embedding for d in resp.data]

        # Index each chunk as a separate document
        for i, (chunk, vect) in enumerate(zip(slim_doc["chunks"], embeddings)):
            chunk_doc = {
                "document_id": file_hash,
                "filename": slim_doc["filename"],
                "mimetype": slim_doc["mimetype"],
                "page": chunk["page"],
                "text": chunk["text"],
                "chunk_embedding": vect,
                "owner": owner_user_id,
                "indexed_time": datetime.datetime.now().isoformat()
            }
            chunk_id = f"{file_hash}_{i}"
            await clients.opensearch.index(index=INDEX_NAME, id=chunk_id, body=chunk_doc)
        return {"status": "indexed", "id": file_hash}

    async def process_upload_file(self, upload_file, owner_user_id: str = None):
        """Process an uploaded file from form data"""
        sha256 = hashlib.sha256()
        tmp = tempfile.NamedTemporaryFile(delete=False)
        try:
            while True:
                chunk = await upload_file.read(1 << 20)
                if not chunk:
                    break
                sha256.update(chunk)
                tmp.write(chunk)
            tmp.flush()

            file_hash = sha256.hexdigest()
            exists = await clients.opensearch.exists(index=INDEX_NAME, id=file_hash)
            if exists:
                return {"status": "unchanged", "id": file_hash}

            result = await self.process_file_common(tmp.name, file_hash, owner_user_id=owner_user_id)
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
            "content_length": len(full_content)
        }

    async def process_single_file_task(self, upload_task, file_path: str):
        """Process a single file and update task tracking - used by task service"""
        from models.tasks import TaskStatus
        import time
        import asyncio
        
        file_task = upload_task.file_tasks[file_path]
        file_task.status = TaskStatus.RUNNING
        file_task.updated_at = time.time()
        
        try:
            # Check if file already exists in index
            loop = asyncio.get_event_loop()
            
            # Run CPU-intensive docling processing in separate process
            slim_doc = await loop.run_in_executor(self.process_pool, process_document_sync, file_path)
            
            # Check if already indexed
            exists = await clients.opensearch.exists(index=INDEX_NAME, id=slim_doc["id"])
            if exists:
                result = {"status": "unchanged", "id": slim_doc["id"]}
            else:
                # Generate embeddings and index (I/O bound, keep in main process)
                texts = [c["text"] for c in slim_doc["chunks"]]
                resp = await clients.patched_async_client.embeddings.create(model=EMBED_MODEL, input=texts)
                embeddings = [d.embedding for d in resp.data]

                # Index each chunk
                for i, (chunk, vect) in enumerate(zip(slim_doc["chunks"], embeddings)):
                    chunk_doc = {
                        "document_id": slim_doc["id"],
                        "filename": slim_doc["filename"],
                        "mimetype": slim_doc["mimetype"],
                        "page": chunk["page"],
                        "text": chunk["text"],
                        "chunk_embedding": vect
                    }
                    chunk_id = f"{slim_doc['id']}_{i}"
                    await clients.opensearch.index(index=INDEX_NAME, id=chunk_id, body=chunk_doc)
                
                result = {"status": "indexed", "id": slim_doc["id"]}
            
            result["path"] = file_path
            file_task.status = TaskStatus.COMPLETED
            file_task.result = result
            upload_task.successful_files += 1
            
        except Exception as e:
            print(f"[ERROR] Failed to process file {file_path}: {e}")
            import traceback
            traceback.print_exc()
            file_task.status = TaskStatus.FAILED  
            file_task.error = str(e)
            upload_task.failed_files += 1
        finally:
            file_task.updated_at = time.time()
            upload_task.processed_files += 1
            upload_task.updated_at = time.time()
            
            if upload_task.processed_files >= upload_task.total_files:
                upload_task.status = TaskStatus.COMPLETED