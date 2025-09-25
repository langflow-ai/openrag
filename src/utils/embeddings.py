from utils.logging_config import get_logger


logger = get_logger(__name__)

def get_embedding_dimensions(model_name: str) -> int:
    """Get the embedding dimensions for a given model name."""
    # OpenAI models
    openai_models = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    # Ollama models (common embedding models)
    ollama_models = {
        "nomic-embed-text": 768,
        "all-minilm": 384,
        "mxbai-embed-large": 1024,
    }

    # Watson/IBM models
    watsonx_models = {
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

    # Check all model dictionaries
    all_models = {**openai_models, **ollama_models, **watsonx_models}

    if model_name in all_models:
        dimensions = all_models[model_name]
        logger.info(f"Found dimensions for model '{model_name}': {dimensions}")
        return dimensions

    # Default fallback
    default_dimensions = 1536
    logger.warning(
        f"Unknown embedding model '{model_name}', using default dimensions: {default_dimensions}"
    )
    return default_dimensions


def create_dynamic_index_body(embedding_model: str) -> dict:
    """Create a dynamic index body configuration based on the embedding model."""
    dimensions = get_embedding_dimensions(embedding_model)

    return {
        "settings": {
            "index": {"knn": True},
            "number_of_shards": 1,
            "number_of_replicas": 1,
        },
        "mappings": {
            "properties": {
                "document_id": {"type": "keyword"},
                "filename": {"type": "keyword"},
                "mimetype": {"type": "keyword"},
                "page": {"type": "integer"},
                "text": {"type": "text"},
                "chunk_embedding": {
                    "type": "knn_vector",
                    "dimension": dimensions,
                    "method": {
                        "name": "disk_ann",
                        "engine": "jvector",
                        "space_type": "l2",
                        "parameters": {"ef_construction": 100, "m": 16},
                    },
                },
                "source_url": {"type": "keyword"},
                "connector_type": {"type": "keyword"},
                "owner": {"type": "keyword"},
                "allowed_users": {"type": "keyword"},
                "allowed_groups": {"type": "keyword"},
                "user_permissions": {"type": "object"},
                "group_permissions": {"type": "object"},
                "created_time": {"type": "date"},
                "modified_time": {"type": "date"},
                "indexed_time": {"type": "date"},
                "metadata": {"type": "object"},
            }
        },
    }