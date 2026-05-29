from utils.embedding_fields import build_knn_vector_field, get_embedding_field_name
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def create_index_body(
    embedding_model: str | None = None,
    embedding_dimensions: int | None = None,
) -> dict:
    """Create a static index body configuration.

    Returns:
        OpenSearch index body configuration
    """
    from config.embedding_constants import OPENAI_DEFAULT_EMBEDDING_MODEL
    from config.settings import (
        ACL_PRINCIPAL_LABELS_MAPPING,
        VECTOR_DIM,
        get_openrag_config,
    )

    resolved_embedding_model = (
        embedding_model
        or get_openrag_config().knowledge.embedding_model
        or OPENAI_DEFAULT_EMBEDDING_MODEL
    )

    properties = {
        "document_id": {"type": "keyword"},
        "filename": {"type": "keyword"},
        "mimetype": {"type": "keyword"},
        "page": {"type": "integer"},
        "text": {"type": "text"},
        # Legacy field - kept for backward compatibility and for clusters where
        # Langflow cannot perform mapping updates with a DLS-filtered JWT.
        "chunk_embedding": build_knn_vector_field(VECTOR_DIM),
        # Track which embedding model was used for this chunk
        "embedding_model": {"type": "keyword"},
        "embedding_dimensions": {"type": "integer"},
        "source_url": {"type": "keyword"},
        "connector_type": {"type": "keyword"},
        "ingest_run_id": {"type": "keyword"},
        "owner": {"type": "keyword"},
        "owner_email": {"type": "keyword"},
        "allowed_users": {"type": "keyword"},
        "allowed_groups": {"type": "keyword"},
        "allowed_principals": {"type": "keyword"},
        "allowed_principal_labels": ACL_PRINCIPAL_LABELS_MAPPING,
        "created_time": {"type": "date"},
        "modified_time": {"type": "date"},
        "indexed_time": {"type": "date"},
        "metadata": {"type": "object"},
    }

    if embedding_dimensions:
        properties[get_embedding_field_name(resolved_embedding_model)] = build_knn_vector_field(
            embedding_dimensions
        )

    return {
        "settings": {"index": {"knn": True}, "number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {"properties": properties},
    }
