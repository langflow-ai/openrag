import httpx
from config.settings import OLLAMA_EMBEDDING_DIMENSIONS, OPENAI_EMBEDDING_DIMENSIONS, VECTOR_DIM, WATSONX_EMBEDDING_DIMENSIONS
from utils.logging_config import get_logger


logger = get_logger(__name__)


async def _probe_ollama_embedding_dimension(endpoint: str, model_name: str) -> int:
    """Probe Ollama server to get embedding dimension for a model.
    
    Args:
        endpoint: Ollama server endpoint (e.g., "http://localhost:11434")
        model_name: Name of the embedding model
        
    Returns:
        The embedding dimension, or 0 if the probe fails
    """
    try:
        url = f"{endpoint}/api/embeddings"
        test_input = "test"
        
        # Try modern API format first (input parameter)
        payload = {
            "model": model_name,
            "input": test_input
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, timeout=10.0)
                response.raise_for_status()
                data = response.json()
                
                # Check for embedding in response
                if "embedding" in data:
                    dimension = len(data["embedding"])
                    if dimension > 0:
                        logger.info(f"Probed Ollama model '{model_name}': dimension={dimension}")
                        return dimension
                elif "embeddings" in data and len(data["embeddings"]) > 0:
                    dimension = len(data["embeddings"][0])
                    if dimension > 0:
                        logger.info(f"Probed Ollama model '{model_name}': dimension={dimension}")
                        return dimension
            except Exception as e:
                logger.debug(f"Modern API format failed for model '{model_name}': {e}")
                
                # Try legacy API format (prompt parameter)
                legacy_payload = {
                    "model": model_name,
                    "prompt": test_input
                }
                
                try:
                    response = await client.post(url, json=legacy_payload, timeout=10.0)
                    response.raise_for_status()
                    data = response.json()
                    
                    if "embedding" in data:
                        dimension = len(data["embedding"])
                        if dimension > 0:
                            logger.info(f"Probed Ollama model '{model_name}' (legacy): dimension={dimension}")
                            return dimension
                    elif "embeddings" in data and len(data["embeddings"]) > 0:
                        dimension = len(data["embeddings"][0])
                        if dimension > 0:
                            logger.info(f"Probed Ollama model '{model_name}' (legacy): dimension={dimension}")
                            return dimension
                except Exception as legacy_error:
                    logger.warning(f"Failed to probe Ollama model '{model_name}': {legacy_error}")
        
        logger.warning(f"Could not determine dimension for Ollama model '{model_name}'")
        return 0
        
    except Exception as e:
        logger.warning(f"Error probing Ollama embedding dimension for '{model_name}': {e}")
        return 0


async def resolve_embedding_dimension(
    embedding_model: str,
    provider: str = None,
    endpoint: str = None
) -> int:
    """Resolve embedding dimension for a model, with dynamic probing for Ollama.
    
    Args:
        embedding_model: Name of the embedding model
        provider: Provider name (e.g., "ollama", "openai", "watsonx")
        endpoint: Endpoint URL for the provider (required for Ollama probing)
        
    Returns:
        The embedding dimension
    """
    # Try dynamic probing for Ollama
    if provider and provider.lower() == "ollama" and endpoint:
        logger.info(f"Attempting to probe Ollama server for model '{embedding_model}'")
        dimension = await _probe_ollama_embedding_dimension(endpoint, embedding_model)
        if dimension > 0:
            return dimension
        logger.info(f"Probe failed, falling back to static maps for '{embedding_model}'")
    
    # Fall back to static maps
    return get_embedding_dimensions(embedding_model)


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


async def create_dynamic_index_body(
    embedding_model: str,
    provider: str = None,
    endpoint: str = None
) -> dict:
    """Create a dynamic index body configuration based on the embedding model.
    
    Args:
        embedding_model: Name of the embedding model
        provider: Provider name (e.g., "ollama", "openai", "watsonx")
        endpoint: Endpoint URL for the provider (used for Ollama probing)
        
    Returns:
        OpenSearch index body configuration
    """
    dimensions = await resolve_embedding_dimension(embedding_model, provider, endpoint)

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