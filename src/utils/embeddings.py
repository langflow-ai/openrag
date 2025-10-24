import httpx
from config.settings import OPENAI_EMBEDDING_DIMENSIONS, VECTOR_DIM, WATSONX_EMBEDDING_DIMENSIONS
from utils.container_utils import transform_localhost_url
from utils.logging_config import get_logger


logger = get_logger(__name__)


async def _probe_ollama_embedding_dimension(endpoint: str, model_name: str) -> int:
    """Probe Ollama server to get embedding dimension for a model.

    Args:
        endpoint: Ollama server endpoint (e.g., "http://localhost:11434")
        model_name: Name of the embedding model

    Returns:
        The embedding dimension.

    Raises:
        ValueError: If the dimension cannot be determined.
    """
    transformed_endpoint = transform_localhost_url(endpoint)
    url = f"{transformed_endpoint}/api/embeddings"
    test_input = "test"

    async with httpx.AsyncClient() as client:
        errors: list[str] = []

        # Try modern API format first (input parameter)
        modern_payload = {
            "model": model_name,
            "input": test_input,
            "prompt": test_input,
        }

        try:
            response = await client.post(url, json=modern_payload, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            # Check for embedding in response
            if "embedding" in data:
                dimension = len(data["embedding"])
                if dimension > 0:
                    logger.info(
                        f"Probed Ollama model '{model_name}': dimension={dimension}"
                    )
                    return dimension
            elif "embeddings" in data and len(data["embeddings"]) > 0:
                dimension = len(data["embeddings"][0])
                if dimension > 0:
                    logger.info(
                        f"Probed Ollama model '{model_name}': dimension={dimension}"
                    )
                    return dimension

            errors.append("response did not include non-zero embedding vector")
        except Exception as modern_error:  # noqa: BLE001 - log and fall back to legacy payload
            logger.debug(
                "Modern Ollama embeddings API probe failed",
                model=model_name,
                endpoint=transformed_endpoint,
                error=str(modern_error),
            )
            errors.append(str(modern_error))

        # Try legacy API format (prompt parameter)
        legacy_payload = {
            "model": model_name,
            "prompt": test_input,
        }

        try:
            response = await client.post(url, json=legacy_payload, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            if "embedding" in data:
                dimension = len(data["embedding"])
                if dimension > 0:
                    logger.info(
                        f"Probed Ollama model '{model_name}' (legacy): dimension={dimension}"
                    )
                    return dimension
            elif "embeddings" in data and len(data["embeddings"]) > 0:
                dimension = len(data["embeddings"][0])
                if dimension > 0:
                    logger.info(
                        f"Probed Ollama model '{model_name}' (legacy): dimension={dimension}"
                    )
                    return dimension

            errors.append("legacy response did not include non-zero embedding vector")
        except Exception as legacy_error:  # noqa: BLE001 - collect and raise a helpful error later
            logger.warning(
                "Legacy Ollama embeddings API probe failed",
                model=model_name,
                endpoint=transformed_endpoint,
                error=str(legacy_error),
            )
            errors.append(str(legacy_error))
    
    # remove the first instance of this error to show either it or the actual error from any of the two methods
    errors.remove("All connection attempts failed") 

    raise ValueError(
        f"Failed to determine embedding dimensions for Ollama model '{model_name}'. "
        f"Verify the Ollama server at '{endpoint}' is reachable and the model is available. "
        f"Error: {errors[0]}"
    )


async def get_embedding_dimensions(model_name: str, provider: str = None, endpoint: str = None) -> int:
    """Get the embedding dimensions for a given model name."""

    if provider and provider.lower() == "ollama":
        if not endpoint:
            raise ValueError(
                "Ollama endpoint is required to determine embedding dimensions. Please provide a valid endpoint."
            )
        return await _probe_ollama_embedding_dimension(endpoint, model_name)

    # Check all model dictionaries
    all_models = {**OPENAI_EMBEDDING_DIMENSIONS, **WATSONX_EMBEDDING_DIMENSIONS}

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
    dimensions = await get_embedding_dimensions(embedding_model, provider, endpoint)

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
                "embedding_dimensions": {"type": "integer"},
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
