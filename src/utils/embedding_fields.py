"""
Utility functions for managing dynamic embedding field names in OpenSearch.

This module provides helpers for:
- Normalizing embedding model names to valid OpenSearch field names
- Generating dynamic field names based on embedding models
- Building the shared knn_vector field mapping used across the codebase
- Ensuring embedding fields exist in the OpenSearch index
"""

from dataclasses import dataclass
from typing import Any

from utils.logging_config import get_logger

logger = get_logger(__name__)

EMBEDDING_SPACE_SEPARATOR = ":"
LEGACY_EMBEDDING_ROUTE_PREFIX = "legacy:"
INDEXED_EMBEDDING_ROUTE_PREFIX = "space:"


@dataclass(frozen=True)
class EmbeddingSpace:
    """One indexed vector space and the provider route needed to query it."""

    space_id: str
    route_model: str
    field_identity: str
    legacy: bool = False


def get_embedding_space_id(provider: str, model_name: str) -> str:
    """Return the stable provider-qualified identity of an embedding space."""
    provider_key = (provider or "").strip().lower()
    model = (model_name or "").strip()
    if not provider_key or not model:
        raise ValueError("Embedding provider and model name are required")
    return f"{provider_key}{EMBEDDING_SPACE_SEPARATOR}{model}"


def split_embedding_space_id(space_id: str) -> tuple[str | None, str]:
    """Split ``provider:model`` while leaving legacy model-only ids intact."""
    value = (space_id or "").strip()
    provider, separator, model = value.partition(EMBEDDING_SPACE_SEPARATOR)
    if separator and provider and model:
        return provider.lower(), model
    return None, value


def build_embedding_space_aggregation(
    *,
    size: int,
    qualified_after: dict[str, Any] | None = None,
    legacy_after: dict[str, Any] | None = None,
    include_qualified: bool = True,
    include_legacy: bool = True,
) -> dict[str, Any]:
    """Build pageable discovery aggregations for exact and legacy vector spaces."""
    aggregations: dict[str, Any] = {}
    if include_qualified:
        composite: dict[str, Any] = {
            "size": size,
            "sources": [{"space_id": {"terms": {"field": "embedding_space_id"}}}],
        }
        if qualified_after:
            composite["after"] = qualified_after
        aggregations["embedding_spaces"] = {"composite": composite}

    if include_legacy:
        composite = {
            "size": size,
            "sources": [{"model": {"terms": {"field": "embedding_model"}}}],
        }
        if legacy_after:
            composite["after"] = legacy_after
        aggregations["legacy_embedding_models"] = {"composite": composite}
    return aggregations


def embedding_space_after_keys(
    result: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return composite pagination cursors for exact and legacy aggregations."""
    aggregations = result.get("aggregations", {})
    qualified_after = aggregations.get("embedding_spaces", {}).get("after_key")
    legacy_after = aggregations.get("legacy_embedding_models", {}).get("after_key")
    return qualified_after, legacy_after


def embedding_spaces_from_aggregation(result: dict[str, Any]) -> list[EmbeddingSpace]:
    """Convert an OpenSearch aggregation response into retrieval identities."""
    aggregations = result.get("aggregations", {})
    qualified_buckets = aggregations.get("embedding_spaces", {}).get("buckets", [])
    legacy_buckets = aggregations.get("legacy_embedding_models", {}).get("buckets", [])

    spaces: list[EmbeddingSpace] = []
    seen: set[str] = set()
    for bucket in qualified_buckets:
        key = bucket.get("key")
        space_id = str(key.get("space_id") if isinstance(key, dict) else key or "").strip()
        if not space_id or space_id in seen:
            continue
        seen.add(space_id)
        spaces.append(
            EmbeddingSpace(
                space_id=space_id,
                route_model=f"{INDEXED_EMBEDDING_ROUTE_PREFIX}{space_id}",
                field_identity=space_id,
            )
        )

    for bucket in legacy_buckets:
        key = bucket.get("key")
        model = str(key.get("model") if isinstance(key, dict) else key or "").strip()
        space_id = f"{LEGACY_EMBEDDING_ROUTE_PREFIX}{model}"
        if not model or space_id in seen:
            continue
        seen.add(space_id)
        spaces.append(
            EmbeddingSpace(
                space_id=space_id,
                route_model=space_id,
                field_identity=model,
                legacy=True,
            )
        )
    return spaces


def build_knn_vector_field(dimension: int) -> dict[str, Any]:
    """Build a knn_vector field mapping for OpenSearch using OpenRAG's JVector settings.

    All knn_vector fields in the documents index share the same JVector/DiskANN
    method configuration, differing only in their vector dimension. This helper
    is the single source of truth for that configuration so tuning changes
    apply uniformly wherever an embedding field is declared.

    Args:
        dimension: Vector dimension for the embedding model that will populate
            the field. Must match the output dimension of the embedding model.

    Returns:
        A fresh dict suitable for use as a field entry in an OpenSearch
        mapping's ``properties``. Each call returns a new dict, so callers
        may safely extend it in place (for example, to add ``advanced.*``
        parameters for a specific field) without affecting other call sites.
    """
    from config.settings import KNN_EF_CONSTRUCTION, KNN_M

    return {
        "type": "knn_vector",
        "dimension": dimension,
        "method": {
            "name": "disk_ann",
            "engine": "jvector",
            "space_type": "l2",
            "parameters": {
                "ef_construction": KNN_EF_CONSTRUCTION,
                "m": KNN_M,
            },
        },
    }


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
    dimensions: int = 0,
) -> str:
    """
    Ensure that an embedding field for the specified model exists in the OpenSearch index.
    If the field doesn't exist, it will be added dynamically using PUT mapping API.

    Args:
        opensearch_client: OpenSearch client instance
        model_name: The embedding model name
        index_name: OpenSearch index name (defaults to get_index_name() from settings)

    Returns:
        The field name that was ensured to exist

    Raises:
        Exception: If unable to add the field mapping
    """
    from config.settings import get_index_name

    if index_name is None:
        index_name = get_index_name()

    field_name = get_embedding_field_name(model_name)

    if dimensions == 0:
        raise ValueError("Dimensions must be provided")

    logger.info(
        "Ensuring embedding field exists",
        field_name=field_name,
        model_name=model_name,
        dimensions=dimensions,
    )

    async def _get_field_definition() -> dict[str, Any]:
        try:
            mapping = await opensearch_client.indices.get_mapping(index=index_name)
        except Exception as e:
            logger.debug(
                "Failed to fetch mapping before ensuring embedding field",
                index=index_name,
                error=str(e),
            )
            return {}

        for index_info in mapping.values():
            properties = index_info.get("mappings", {}).get("properties", {})
            if isinstance(properties, dict) and field_name in properties:
                return properties[field_name]
        return {}

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
            field_name: build_knn_vector_field(dimensions),
            # Also ensure the embedding_model tracking field exists as keyword
            "embedding_model": {"type": "keyword"},
            "embedding_provider": {"type": "keyword"},
            "embedding_space_id": {"type": "keyword"},
            "embedding_dimensions": {"type": "integer"},
        }
    }

    try:
        # Try to add the mapping
        # OpenSearch will ignore if field already exists
        await opensearch_client.indices.put_mapping(index=index_name, body=mapping)
        logger.info(
            "Successfully ensured embedding field exists",
            field_name=field_name,
            model_name=model_name,
        )
    except Exception as e:
        # Check if the field was created by a concurrent request
        check_def = await _get_field_definition()
        if check_def.get("type") == "knn_vector":
            logger.info(
                "Embedding field already exists as knn_vector (race condition handled)",
                field_name=field_name,
                model_name=model_name,
            )
            return field_name

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
