# app.py

import os
os.environ['USE_CPU_ONLY'] = 'true'

import json
import hashlib
import tempfile
import asyncio

from starlette.applications import Starlette
from starlette.requests     import Request
from starlette.responses    import JSONResponse
from starlette.routing      import Route

import aiofiles
from opensearchpy import AsyncOpenSearch
from opensearchpy._async.http_aiohttp import AIOHttpConnection
from docling.document_converter import DocumentConverter


# Initialize Docling converter
converter = DocumentConverter()  # basic converter; tweak via PipelineOptions if you need OCR, etc. :contentReference[oaicite:0]{index=0}

# Initialize Async OpenSearch (adjust hosts/auth as needed)
es = AsyncOpenSearch(
    hosts=[{"host": "localhost", "port": 9200}],
    connection_class=AIOHttpConnection,
    scheme="https",
    use_ssl=True,
    verify_certs=False,
    ssl_assert_fingerprint=None,
    http_auth=("admin","OSisgendb1!"),
    http_compress=True,
)

INDEX_NAME = "documents"

index_body = {
    "settings": {"number_of_shards":1, "number_of_replicas":1},
    "mappings": {
        "properties": {
            "origin": {
                "properties": {
                    "binary_hash": {"type":"keyword"}
                }
            }
        }
    }
}
async def init_index():
    if not await es.indices.exists(index=INDEX_NAME):
        await es.indices.create(index=INDEX_NAME, body=index_body)
        print(f"Created index '{INDEX_NAME}'")
    else:
        print(f"Index '{INDEX_NAME}' already exists, skipping creation.")

# Index will be initialized when the app starts


# ——————————————
# CORE PROCESSING LOGIC
# ——————————————

async def process_file_on_disk(path: str):
    """
    1. Compute SHA256 hash by streaming the file in chunks.
    2. If OpenSearch already has a doc with that ID, skip.
    3. Otherwise, run Docling.convert(path) → JSON → index into OpenSearch.
    """
    # 1) compute hash
    sha256 = hashlib.sha256()
    async with aiofiles.open(path, "rb") as f:
        while True:
            chunk = await f.read(1 << 20)  # 1 MiB
            if not chunk:
                break
            sha256.update(chunk)
    file_hash = sha256.hexdigest()

    # 2) check in OpenSearch
    exists = await es.exists(index=INDEX_NAME, id=file_hash)
    if exists:
        return {"path": path, "status": "unchanged", "id": file_hash}

    # 3) parse + index
    result = converter.convert(path)
    doc_dict = result.document.export_to_dict()
    await es.index(index=INDEX_NAME, id=file_hash, body=doc_dict)

    return {"path": path, "status": "indexed", "id": file_hash}


async def upload(request: Request):
    """
    POST /upload
    Form-data with a `file` field. Streams to disk + processes it.
    """
    form = await request.form()
    upload_file = form["file"]  # starlette.datastructures.UploadFile

    # stream into a temp file while hashing
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
        # if you prefer the Datastax pattern for naming IDs, see:
        # https://github.com/datastax/astra-assistants-api/blob/main/impl/utils.py#L229 :contentReference[oaicite:1]{index=1}

        # check + index
        exists = await es.exists(index=INDEX_NAME, id=file_hash)
        if exists:
            return JSONResponse({"status": "unchanged", "id": file_hash})

        result = converter.convert(tmp.name)
        doc_dict = result.document.export_to_dict()
        await es.index(index=INDEX_NAME, id=file_hash, body=doc_dict)

        return JSONResponse({"status": "indexed", "id": file_hash})

    finally:
        tmp.close()
        os.remove(tmp.name)


async def upload_path(request: Request):
    """
    POST /upload_path
    JSON body: { "path": "/absolute/path/to/dir" }
    Recursively processes every file found there in parallel.
    """
    payload = await request.json()
    base_dir = payload.get("path")
    if not base_dir or not os.path.isdir(base_dir):
        return JSONResponse({"error": "Invalid path"}, status_code=400)

    tasks = []
    for root, _, files in os.walk(base_dir):
        for fn in files:
            full = os.path.join(root, fn)
            tasks.append(process_file_on_disk(full))

    results = await asyncio.gather(*tasks)
    return JSONResponse({"results": results})


app = Starlette(debug=True, routes=[
    Route("/upload",      upload,       methods=["POST"]),
    Route("/upload_path", upload_path,  methods=["POST"]),
])


if __name__ == "__main__":
    import uvicorn

    # Initialize index before starting server
    asyncio.run(init_index())
    
    uvicorn.run(
        "app:app",        # "module:variable"
        host="0.0.0.0",
        port=8000,
        reload=True,      # dev only
    )
