"""Embedding model constants and dimensions."""

EMBED_MODEL = "text-embedding-3-small"

OPENAI_EMBEDDING_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

WATSONX_EMBEDDING_DIMENSIONS = {
    # IBM Models
    "ibm/granite-embedding-107m-multilingual": 384,
    "ibm/granite-embedding-278m-multilingual": 1024,
    "ibm/slate-125m-english-rtrvr": 768,
    "ibm/slate-125m-english-rtrvr-v2": 768,
    "ibm/slate-30m-english-rtrvr": 384,
    "ibm/slate-30m-english-rtrvr-v2": 384,
    # Third Party Models
    "intfloat/multilingual-e5-large": 1024,
    "sentence-transformers/all-minilm-l6-v2": 384,
}
