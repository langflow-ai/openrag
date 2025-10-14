"""
Utility functions for managing dynamic embedding field names in OpenSearch.

This module provides helpers for:
- Normalizing embedding model names to valid OpenSearch field names
- Generating dynamic field names based on embedding models
- Ensuring embedding fields exist in the OpenSearch index
"""

from typing import Dict, Any

from utils.logging_config import get_logger

logger = get_logger(__name__)


def normalize_model_name(model_name: str) -> str:
    """
    Convert an embedding model name to a valid OpenSearch field suffix.

    Examples:
        - "text-embedding-3-small" -> "text_embedding_3_small"
        - "nomic-embed-text:latest" -> "nomic_embed_text_latest"
        - "ibm/slate-125m-english-rtrvr" -> "ibm_slate_125m_english_rtrvr"

    Args:
        model_name: The embedding model name (e.g., from OpenAI, Ollama, Watsonx)

    Returns:
        Normalized string safe for use as OpenSearch field name suffix
    """
    normalized = model_name.lower()
    # Replace common separators with underscores
    normalized = normalized.replace("-", "_")
    normalized = normalized.replace(":", "_")
    normalized = normalized.replace("/", "_")
    normalized = normalized.replace(".", "_")
    # Remove any other non-alphanumeric characters
    normalized = "".join(c if c.isalnum() or c == "_" else "_" for c in normalized)
    # Remove duplicate underscores
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    # Remove leading/trailing underscores
    normalized = normalized.strip("_")

    return normalized


def get_embedding_field_name(model_name: str) -> str:
    """
    Get the OpenSearch field name for storing embeddings from a specific model.

    Args:
        model_name: The embedding model name

    Returns:
        Field name in format: chunk_embedding_{normalized_model_name}

    Examples:
        >>> get_embedding_field_name("text-embedding-3-small")
        'chunk_embedding_text_embedding_3_small'
        >>> get_embedding_field_name("nomic-embed-text")
        'chunk_embedding_nomic_embed_text'
    """
    normalized = normalize_model_name(model_name)
    return f"chunk_embedding_{normalized}"


async def ensure_embedding_field_exists(
    opensearch_client,
    model_name: str,
    index_name: str = None,
) -> str:
    """
    Ensure that an embedding field for the specified model exists in the OpenSearch index.
    If the field doesn't exist, it will be added dynamically using PUT mapping API.

    Args:
        opensearch_client: OpenSearch client instance
        model_name: The embedding model name
        index_name: OpenSearch index name (defaults to INDEX_NAME from settings)

    Returns:
        The field name that was ensured to exist

    Raises:
        Exception: If unable to add the field mapping
    """
    from config.settings import INDEX_NAME
    from utils.embeddings import get_embedding_dimensions

    if index_name is None:
        index_name = INDEX_NAME

    field_name = get_embedding_field_name(model_name)
    dimensions = await get_embedding_dimensions(model_name)

    logger.info(
        "Ensuring embedding field exists",
        field_name=field_name,
        model_name=model_name,
        dimensions=dimensions,
    )

    async def _get_field_definition() -> Dict[str, Any]:
        try:
            mapping = await opensearch_client.indices.get_mapping(index=index_name)
        except Exception as e:
            logger.debug(
                "Failed to fetch mapping before ensuring embedding field",
                index=index_name,
                error=str(e),
            )
            return {}

        properties = mapping.get(index_name, {}).get("mappings", {}).get("properties", {})
        return properties.get(field_name, {}) if isinstance(properties, dict) else {}

    existing_definition = await _get_field_definition()
    if existing_definition:
        if existing_definition.get("type") != "knn_vector":
            raise RuntimeError(
                f"Field '{field_name}' already exists with incompatible type '{existing_definition.get('type')}'"
            )
        return field_name

    # Define the field mapping for both the vector field and the tracking field
    mapping = {
        "properties": {
            field_name: {
                "type": "knn_vector",
                "dimension": dimensions,
                "method": {
                    "name": "disk_ann",
                    "engine": "jvector",
                    "space_type": "l2",
                    "parameters": {"ef_construction": 100, "m": 16},
                },
            },
            # Also ensure the embedding_model tracking field exists as keyword
            "embedding_model": {
                "type": "keyword"
            },
            "embedding_dimensions": {
                "type": "integer"
            },
        }
    }

    try:
        # Try to add the mapping
        # OpenSearch will ignore if field already exists
        await opensearch_client.indices.put_mapping(
            index=index_name,
            body=mapping
        )
        logger.info(
            "Successfully ensured embedding field exists",
            field_name=field_name,
            model_name=model_name,
        )
    except Exception as e:
        logger.error(
            "Failed to add embedding field mapping",
            field_name=field_name,
            model_name=model_name,
            error=str(e),
        )
        raise

    # Verify mapping was applied correctly
    new_definition = await _get_field_definition()
    if new_definition.get("type") != "knn_vector":
        raise RuntimeError(
            f"Failed to ensure '{field_name}' is mapped as knn_vector. Current definition: {new_definition}"
        )

    return field_name
