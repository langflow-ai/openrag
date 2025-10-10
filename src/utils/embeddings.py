from config.settings import OLLAMA_EMBEDDING_DIMENSIONS, OPENAI_EMBEDDING_DIMENSIONS, VECTOR_DIM, WATSONX_EMBEDDING_DIMENSIONS
from utils.logging_config import get_logger


logger = get_logger(__name__)

def get_embedding_dimensions(model_name: str) -> int:
    """Get the embedding dimensions for a given model name."""

    # Check all model dictionaries
    all_models = {**OPENAI_EMBEDDING_DIMENSIONS, **OLLAMA_EMBEDDING_DIMENSIONS, **WATSONX_EMBEDDING_DIMENSIONS}

    model_name = model_name.lower().strip().split(":")[0]

    if model_name in all_models:
        dimensions = all_models[model_name]
        logger.info(f"Found dimensions for model '{model_name}': {dimensions}")
        return dimensions

    logger.warning(
        f"Unknown embedding model '{model_name}', using default dimensions: {VECTOR_DIM}"
    )
    return VECTOR_DIM


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
                # Legacy field - kept for backward compatibility
                # New documents will use chunk_embedding_{model_name} fields
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
                # Track which embedding model was used for this chunk
                "embedding_model": {"type": "keyword"},
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