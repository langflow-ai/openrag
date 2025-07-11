# app.py

import os
from collections import defaultdict

os.environ['USE_CPU_ONLY'] = 'true'

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
from agentd.patch import patch_openai_with_mcp
from openai import OpenAI

# Initialize Docling converter
converter = DocumentConverter()  # basic converter; tweak via PipelineOptions if you need OCR, etc.

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

client = patch_openai_with_mcp(OpenAI())  # Get the patched client back

async def init_index():
    if not await es.indices.exists(index=INDEX_NAME):
        await es.indices.create(index=INDEX_NAME, body=index_body)
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

    #exists = await es.exists(index=INDEX_NAME, id=file_hash)
    #if exists:
    #    return {"status": "unchanged", "id": file_hash}

    # convert and extract
    # TODO: Check if docling can handle in-memory bytes instead of file path
    # This would eliminate the need for temp files in upload flow
    result = converter.convert(file_path)
    full_doc = result.document.export_to_dict()
    slim_doc = extract_relevant(full_doc)

    texts = [c["text"] for c in slim_doc["chunks"]]
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
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
        await es.index(index=INDEX_NAME, id=chunk_id, body=chunk_doc)
    return {"status": "indexed", "id": file_hash}

async def process_file_on_disk(path: str):
    """
    Process a file already on disk.
    """
    result = await process_file_common(path)
    result["path"] = path
    return result

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
        #exists = await es.exists(index=INDEX_NAME, id=file_hash)
        #if exists:
        #    return JSONResponse({"status": "unchanged", "id": file_hash})

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

    tasks = [process_file_on_disk(os.path.join(root, fn))
             for root, _, files in os.walk(base_dir)
             for fn in files]

    results = await asyncio.gather(*tasks)
    return JSONResponse({"results": results})

async def search(request: Request):
    payload = await request.json()
    query = payload.get("query")
    if not query:
        return JSONResponse({"error": "Query is required"}, status_code=400)

    # Embed the query
    resp = client.embeddings.create(model=EMBED_MODEL, input=[query])
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

    results = await es.search(index=INDEX_NAME, body=search_body)
    
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
    
    return JSONResponse({"results": chunks})

app = Starlette(debug=True, routes=[
    Route("/upload",      upload,       methods=["POST"]),
    Route("/upload_path", upload_path,  methods=["POST"]),
    Route("/search",      search,       methods=["POST"]),
])

if __name__ == "__main__":
    import uvicorn
    asyncio.run(init_index())
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )

