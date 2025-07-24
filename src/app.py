# app.py

import os
from collections import defaultdict
from typing import Any
import uuid
import time
import random
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ProcessPoolExecutor
import multiprocessing

from agent import async_chat, async_langflow

import hashlib
import tempfile
import asyncio

from starlette.applications import Starlette
from starlette.requests     import Request
from starlette.responses    import JSONResponse, StreamingResponse
from starlette.routing      import Route

import aiofiles
from opensearchpy import AsyncOpenSearch
from opensearchpy._async.http_aiohttp import AIOHttpConnection
from docling.document_converter import DocumentConverter
from agentd.patch import patch_openai_with_mcp
from openai import AsyncOpenAI
from agentd.tool_decorator import tool
from dotenv import load_dotenv

load_dotenv()
load_dotenv("../")

import torch
print("CUDA available:", torch.cuda.is_available())
print("CUDA version PyTorch was built with:", torch.version.cuda)

# Initialize Docling converter
converter = DocumentConverter()  # basic converter; tweak via PipelineOptions if you need OCR, etc.

# Initialize Async OpenSearch (adjust hosts/auth as needed)
opensearch_host = os.getenv("OPENSEARCH_HOST", "localhost")
opensearch_port = int(os.getenv("OPENSEARCH_PORT", "9200"))
opensearch_username = os.getenv("OPENSEARCH_USERNAME", "admin")
opensearch_password = os.getenv("OPENSEARCH_PASSWORD")
langflow_url = os.getenv("LANGFLOW_URL", "http://localhost:7860")
flow_id = os.getenv("FLOW_ID")
langflow_key = os.getenv("LANGFLOW_SECRET_KEY")



opensearch = AsyncOpenSearch(
    hosts=[{"host": opensearch_host, "port": opensearch_port}],
    connection_class=AIOHttpConnection,
    scheme="https",
    use_ssl=True,
    verify_certs=False,
    ssl_assert_fingerprint=None,
    http_auth=(opensearch_username, opensearch_password),
    http_compress=True,
)

INDEX_NAME = "documents"
VECTOR_DIM = 1536  # e.g. text-embedding-3-small output size
EMBED_MODEL = "text-embedding-3-small"
index_body = {
    "settings": {
        "index": {"knn": True},
        "number_of_shards": 1,
        "number_of_replicas": 1
    },
    "mappings": {
        "properties": {
            "document_id": { "type": "keyword" },
            "filename":    { "type": "keyword" },
            "mimetype":    { "type": "keyword" },
            "page":        { "type": "integer" },
            "text":        { "type": "text" },
            "chunk_embedding": {
                "type": "knn_vector",
                "dimension": VECTOR_DIM,
                "method": {
                    "name":       "disk_ann",
                    "engine":     "jvector",
                    "space_type": "l2",
                    "parameters": {
                        "ef_construction": 100,
                        "m":               16
                    }
                }
            }
        }
    }
}

langflow_client = AsyncOpenAI(
    base_url=f"{langflow_url}/api/v1",
    api_key=langflow_key
)
patched_async_client = patch_openai_with_mcp(AsyncOpenAI())  # Get the patched client back

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running" 
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class FileTask:
    file_path: str
    status: TaskStatus = TaskStatus.PENDING
    result: dict = None
    error: str = None
    retry_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

@dataclass 
class UploadTask:
    task_id: str
    total_files: int
    processed_files: int = 0
    successful_files: int = 0
    failed_files: int = 0
    file_tasks: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

task_store = {}
background_tasks = set()

# GPU device detection
def detect_gpu_devices():
    """Detect if GPU devices are actually available"""
    try:
        import torch
        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            return True, torch.cuda.device_count()
    except ImportError:
        pass
    
    try:
        import subprocess
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
        if result.returncode == 0:
            return True, "detected"
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    return False, 0

# GPU and concurrency configuration
HAS_GPU_DEVICES, GPU_COUNT = detect_gpu_devices()

if HAS_GPU_DEVICES:
    # GPU mode with actual GPU devices: Lower concurrency due to memory constraints
    DEFAULT_WORKERS = min(4, multiprocessing.cpu_count() // 2)
    print(f"GPU mode enabled with {GPU_COUNT} GPU(s) - using limited concurrency ({DEFAULT_WORKERS} workers)")
elif HAS_GPU_DEVICES:
    # GPU mode requested but no devices found: Use full CPU concurrency
    DEFAULT_WORKERS = multiprocessing.cpu_count()
    print(f"GPU mode requested but no GPU devices found - falling back to full CPU concurrency ({DEFAULT_WORKERS} workers)")
else:
    # CPU mode: Higher concurrency since no GPU memory constraints
    DEFAULT_WORKERS = multiprocessing.cpu_count()
    print(f"CPU-only mode enabled - using full concurrency ({DEFAULT_WORKERS} workers)")

MAX_WORKERS = int(os.getenv("MAX_WORKERS", DEFAULT_WORKERS))
process_pool = ProcessPoolExecutor(max_workers=MAX_WORKERS)

print(f"Process pool initialized with {MAX_WORKERS} workers")

# Global converter cache for worker processes
_worker_converter = None

def get_worker_converter():
    """Get or create a DocumentConverter instance for this worker process"""
    global _worker_converter
    if _worker_converter is None:
        import os
        from docling.document_converter import DocumentConverter
        
        # Configure GPU settings for this worker
        has_gpu_devices, _ = detect_gpu_devices()
        if not has_gpu_devices:
            # Force CPU-only mode in subprocess
            os.environ['USE_CPU_ONLY'] = 'true'
            os.environ['CUDA_VISIBLE_DEVICES'] = ''
            os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
            os.environ['TRANSFORMERS_OFFLINE'] = '0'
            os.environ['TORCH_USE_CUDA_DSA'] = '0'
            
            # Try to disable CUDA in torch if available
            try:
                import torch
                torch.cuda.is_available = lambda: False
            except ImportError:
                pass
        else:
            # GPU mode - let libraries use GPU if available
            os.environ.pop('USE_CPU_ONLY', None)
            os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'  # Still disable progress bars
        
        print(f"🔧 Initializing DocumentConverter in worker process (PID: {os.getpid()})")
        _worker_converter = DocumentConverter()
        print(f"✅ DocumentConverter ready in worker process (PID: {os.getpid()})")
    
    return _worker_converter

def detect_gpu_devices():
    """Detect if GPU devices are actually available"""
    try:
        import torch
        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            return True, torch.cuda.device_count()
    except ImportError:
        pass
    
    try:
        import subprocess
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
        if result.returncode == 0:
            return True, "detected"
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    return False, 0

def process_document_sync(file_path: str):
    """Synchronous document processing function for multiprocessing"""
    import hashlib
    from collections import defaultdict
    
    # Get the cached converter for this worker
    converter = get_worker_converter()
    
    # Compute file hash
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            sha256.update(chunk)
    file_hash = sha256.hexdigest()
    
    # Convert with docling
    result = converter.convert(file_path)
    full_doc = result.document.export_to_dict()
    
    # Extract relevant content (same logic as extract_relevant)
    origin = full_doc.get("origin", {})
    texts = full_doc.get("texts", [])

    page_texts = defaultdict(list)
    for txt in texts:
        prov = txt.get("prov", [])
        page_no = prov[0].get("page_no") if prov else None
        if page_no is not None:
            page_texts[page_no].append(txt.get("text", "").strip())

    chunks = []
    for page in sorted(page_texts):
        joined = "\n".join(page_texts[page])
        chunks.append({
            "page": page,
            "text": joined
        })

    return {
        "id": file_hash,
        "filename": origin.get("filename"),
        "mimetype": origin.get("mimetype"),
        "chunks": chunks,
        "file_path": file_path
    }

async def wait_for_opensearch():
    """Wait for OpenSearch to be ready with retries"""
    max_retries = 30
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            await opensearch.info()
            print("OpenSearch is ready!")
            return
        except Exception as e:
            print(f"Attempt {attempt + 1}/{max_retries}: OpenSearch not ready yet ({e})")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
            else:
                raise Exception("OpenSearch failed to become ready")

async def init_index():
    await wait_for_opensearch()
    
    if not await opensearch.indices.exists(index=INDEX_NAME):
        await opensearch.indices.create(index=INDEX_NAME, body=index_body)
        print(f"Created index '{INDEX_NAME}'")
    else:
        print(f"Index '{INDEX_NAME}' already exists, skipping creation.")

def extract_relevant(doc_dict: dict) -> dict:
    """
    Given the full export_to_dict() result:
      - Grabs origin metadata (hash, filename, mimetype)
      - Finds every text fragment in `texts`, groups them by page_no
      - Concatenates each page’s fragments into one string chunk
    Returns a slimmed dict ready for indexing.
    """
    origin = doc_dict.get("origin", {})
    texts = doc_dict.get("texts", [])

    # Group all text fragments by page number
    page_texts = defaultdict(list)
    for txt in texts:
        # Each txt['prov'][0]['page_no'] tells you which page it came from
        prov = txt.get("prov", [])
        page_no = prov[0].get("page_no") if prov else None
        if page_no is not None:
            page_texts[page_no].append(txt.get("text", "").strip())

    # Build an ordered list of {page, text}
    chunks = []
    for page in sorted(page_texts):
        joined = "\n".join(page_texts[page])
        chunks.append({
            "page": page,
            "text": joined
        })

    return {
        "id": origin.get("binary_hash"),
        "filename": origin.get("filename"),
        "mimetype": origin.get("mimetype"),
        "chunks": chunks
    }

async def exponential_backoff_delay(retry_count: int, base_delay: float = 1.0, max_delay: float = 60.0) -> None:
    """Apply exponential backoff with jitter"""
    delay = min(base_delay * (2 ** retry_count) + random.uniform(0, 1), max_delay)
    await asyncio.sleep(delay)

async def process_file_with_retry(file_path: str, max_retries: int = 3) -> dict:
    """Process a file with retry logic - retries everything up to max_retries times"""
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            return await process_file_common(file_path)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                await exponential_backoff_delay(attempt)
                continue
            else:
                raise last_error

async def process_file_common(file_path: str, file_hash: str = None):
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

    exists = await opensearch.exists(index=INDEX_NAME, id=file_hash)
    if exists:
        return {"status": "unchanged", "id": file_hash}

    # convert and extract
    # TODO: Check if docling can handle in-memory bytes instead of file path
    # This would eliminate the need for temp files in upload flow
    result = converter.convert(file_path)
    full_doc = result.document.export_to_dict()
    slim_doc = extract_relevant(full_doc)

    texts = [c["text"] for c in slim_doc["chunks"]]
    resp = await patched_async_client.embeddings.create(model=EMBED_MODEL, input=texts)
    embeddings = [d.embedding for d in resp.data]

    # Index each chunk as a separate document
    for i, (chunk, vect) in enumerate(zip(slim_doc["chunks"], embeddings)):
        chunk_doc = {
            "document_id": file_hash,
            "filename": slim_doc["filename"],
            "mimetype": slim_doc["mimetype"],
            "page": chunk["page"],
            "text": chunk["text"],
            "chunk_embedding": vect
        }
        chunk_id = f"{file_hash}_{i}"
        await opensearch.index(index=INDEX_NAME, id=chunk_id, body=chunk_doc)
    return {"status": "indexed", "id": file_hash}

async def process_file_on_disk(path: str):
    """
    Process a file already on disk.
    """
    result = await process_file_common(path)
    result["path"] = path
    return result

async def process_single_file_task(upload_task: UploadTask, file_path: str) -> None:
    """Process a single file and update task tracking"""
    file_task = upload_task.file_tasks[file_path]
    file_task.status = TaskStatus.RUNNING
    file_task.updated_at = time.time()
    
    try:
        # Check if file already exists in index
        import asyncio
        loop = asyncio.get_event_loop()
        
        # Run CPU-intensive docling processing in separate process
        slim_doc = await loop.run_in_executor(process_pool, process_document_sync, file_path)
        
        # Check if already indexed
        exists = await opensearch.exists(index=INDEX_NAME, id=slim_doc["id"])
        if exists:
            result = {"status": "unchanged", "id": slim_doc["id"]}
        else:
            # Generate embeddings and index (I/O bound, keep in main process)
            texts = [c["text"] for c in slim_doc["chunks"]]
            resp = await patched_async_client.embeddings.create(model=EMBED_MODEL, input=texts)
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
                await opensearch.index(index=INDEX_NAME, id=chunk_id, body=chunk_doc)
            
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

async def background_upload_processor(task_id: str) -> None:
    """Background task to process all files in an upload job with concurrency control"""
    try:
        upload_task = task_store[task_id]
        upload_task.status = TaskStatus.RUNNING
        upload_task.updated_at = time.time()
        
        # Process files with limited concurrency to avoid overwhelming the system
        semaphore = asyncio.Semaphore(MAX_WORKERS * 2)  # Allow 2x process pool size for async I/O
        
        async def process_with_semaphore(file_path: str):
            async with semaphore:
                await process_single_file_task(upload_task, file_path)
        
        tasks = [
            process_with_semaphore(file_path)
            for file_path in upload_task.file_tasks.keys()
        ]
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
    except Exception as e:
        print(f"[ERROR] Background upload processor failed for task {task_id}: {e}")
        import traceback
        traceback.print_exc()
        if task_id in task_store:
            task_store[task_id].status = TaskStatus.FAILED
            task_store[task_id].updated_at = time.time()

async def upload(request: Request):
    form = await request.form()
    upload_file = form["file"]

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
        exists = await opensearch.exists(index=INDEX_NAME, id=file_hash)
        if exists:
            return JSONResponse({"status": "unchanged", "id": file_hash})

        result = await process_file_common(tmp.name, file_hash)
        return JSONResponse(result)

    finally:
        tmp.close()
        os.remove(tmp.name)

async def upload_path(request: Request):
    payload = await request.json()
    base_dir = payload.get("path")
    if not base_dir or not os.path.isdir(base_dir):
        return JSONResponse({"error": "Invalid path"}, status_code=400)

    file_paths = [os.path.join(root, fn)
                  for root, _, files in os.walk(base_dir)
                  for fn in files]
    
    if not file_paths:
        return JSONResponse({"error": "No files found in directory"}, status_code=400)

    task_id = str(uuid.uuid4())
    upload_task = UploadTask(
        task_id=task_id,
        total_files=len(file_paths),
        file_tasks={path: FileTask(file_path=path) for path in file_paths}
    )
    
    task_store[task_id] = upload_task
    
    background_task = asyncio.create_task(background_upload_processor(task_id))
    background_tasks.add(background_task)
    background_task.add_done_callback(background_tasks.discard)
    
    return JSONResponse({
        "task_id": task_id,
        "total_files": len(file_paths),
        "status": "accepted"
    }, status_code=201)

async def upload_context(request: Request):
    """Upload a file and add its content as context to the current conversation"""
    import io
    from docling_core.types.io import DocumentStream
    
    form = await request.form()
    upload_file = form["file"]
    filename = upload_file.filename or "uploaded_document"
    
    # Get optional parameters
    previous_response_id = form.get("previous_response_id")
    endpoint = form.get("endpoint", "langflow")  # default to langflow

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
    result = converter.convert(doc_stream)
    full_doc = result.document.export_to_dict()
    slim_doc = extract_relevant(full_doc)
    
    # Extract all text content
    all_text = []
    for chunk in slim_doc["chunks"]:
        all_text.append(f"Page {chunk['page']}:\n{chunk['text']}")
    
    full_content = "\n\n".join(all_text)
    
    # Send document content as user message to get proper response_id
    document_prompt = f"I'm uploading a document called '{filename}'. Here is its content:\n\n{full_content}\n\nPlease confirm you've received this document and are ready to answer questions about it."
    
    if endpoint == "langflow":
        from agent import async_langflow
        response_text, response_id = await async_langflow(langflow_client, flow_id, document_prompt, previous_response_id=previous_response_id)
    else:  # chat
        from agent import async_chat
        response_text, response_id = await async_chat(patched_async_client, document_prompt, previous_response_id=previous_response_id)
    
    response_data = {
        "status": "context_added",
        "filename": filename,
        "pages": len(slim_doc["chunks"]),
        "content_length": len(full_content),
        "response_id": response_id,
        "confirmation": response_text
    }
    
    return JSONResponse(response_data)

async def task_status(request: Request):
    """Get the status of an upload task"""
    task_id = request.path_params.get("task_id")
    
    if not task_id or task_id not in task_store:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    
    upload_task = task_store[task_id]
    
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
    
    return JSONResponse({
        "task_id": upload_task.task_id,
        "status": upload_task.status.value,
        "total_files": upload_task.total_files,
        "processed_files": upload_task.processed_files,
        "successful_files": upload_task.successful_files,
        "failed_files": upload_task.failed_files,
        "created_at": upload_task.created_at,
        "updated_at": upload_task.updated_at,
        "files": file_statuses
    })

async def search(request: Request):

    payload = await request.json()
    query = payload.get("query")
    if not query:
        return JSONResponse({"error": "Query is required"}, status_code=400)
    return JSONResponse(await search_tool(query))


@tool
async def search_tool(query: str)-> dict[str, Any]:
    """
    Use this tool to search for documents relevant to the query.

    This endpoint accepts POST requests with a query string,

    Args:
        query (str): query string to search the corpus

    Returns:
        dict (str, Any)
                     - {"results": [chunks]} on success
    """
    # Embed the query
    resp = await patched_async_client.embeddings.create(model=EMBED_MODEL, input=[query])
    query_embedding = resp.data[0].embedding
    # Search using vector similarity on individual chunks
    search_body = {
        "query": {
            "knn": {
                "chunk_embedding": {
                    "vector": query_embedding,
                    "k": 10
                }
            }
        },
        "_source": ["filename", "mimetype", "page", "text"],
        "size": 10
    }
    results = await opensearch.search(index=INDEX_NAME, body=search_body)
    # Transform results to match expected format
    chunks = []
    for hit in results["hits"]["hits"]:
        chunks.append({
            "filename": hit["_source"]["filename"],
            "mimetype": hit["_source"]["mimetype"],
            "page": hit["_source"]["page"],
            "text": hit["_source"]["text"],
            "score": hit["_score"]
        })
    return {"results": chunks}

async def chat_endpoint(request):
    data = await request.json()
    prompt = data.get("prompt", "")
    previous_response_id = data.get("previous_response_id")
    stream = data.get("stream", False)

    if not prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    if stream:
        from agent import async_chat_stream
        return StreamingResponse(
            async_chat_stream(patched_async_client, prompt, previous_response_id=previous_response_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Cache-Control"
            }
        )
    else:
        response_text, response_id = await async_chat(patched_async_client, prompt, previous_response_id=previous_response_id)
        response_data = {"response": response_text}
        if response_id:
            response_data["response_id"] = response_id
        return JSONResponse(response_data)

async def langflow_endpoint(request):
    data = await request.json()
    prompt = data.get("prompt", "")
    previous_response_id = data.get("previous_response_id")
    stream = data.get("stream", False)
    
    if not prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    if not langflow_url or not flow_id or not langflow_key:
        return JSONResponse({"error": "LANGFLOW_URL, FLOW_ID, and LANGFLOW_KEY environment variables are required"}, status_code=500)

    try:
        if stream:
            from agent import async_langflow_stream
            return StreamingResponse(
                async_langflow_stream(langflow_client, flow_id, prompt, previous_response_id=previous_response_id),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Cache-Control"
                }
            )
        else:
            response_text, response_id = await async_langflow(langflow_client, flow_id, prompt, previous_response_id=previous_response_id)
            response_data = {"response": response_text}
            if response_id:
                response_data["response_id"] = response_id
            return JSONResponse(response_data)
        
    except Exception as e:
        return JSONResponse({"error": f"Langflow request failed: {str(e)}"}, status_code=500)

app = Starlette(debug=True, routes=[
    Route("/upload",         upload,           methods=["POST"]),
    Route("/upload_context", upload_context,   methods=["POST"]),
    Route("/upload_path",    upload_path,      methods=["POST"]),
    Route("/tasks/{task_id}", task_status,      methods=["GET"]),
    Route("/search",         search,           methods=["POST"]),
    Route("/chat",           chat_endpoint,    methods=["POST"]),
    Route("/langflow",       langflow_endpoint, methods=["POST"]),
])

if __name__ == "__main__":
    import uvicorn
    import atexit

    async def main():
        await init_index()

    # Cleanup process pool on exit
    def cleanup():
        process_pool.shutdown(wait=True)
    
    atexit.register(cleanup)

    asyncio.run(main())
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
