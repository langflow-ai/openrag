from utils.logging_config import get_logger

logger = get_logger(__name__)

async def create_index_body() -> dict:
    """Create a static index body configuration.
        
    Returns:
        OpenSearch index body configuration
    """

    return {
        "settings": {
            "index": {"knn": True},
            "number_of_shards": 1,
            "number_of_replicas": 0
        },
        "mappings": {
            "properties": {
                "document_id": {"type": "keyword"},
                "filename": {"type": "keyword"},
                "mimetype": {"type": "keyword"},
                "page": {"type": "integer"},
                "text": {"type": "text"},
                # Track which embedding model was used for this chunk
                "embedding_model": {"type": "keyword"},
                "embedding_dimensions": {"type": "integer"},
                "source_url": {"type": "keyword"},
                "connector_type": {"type": "keyword"},
                "owner": {"type": "keyword"},
                "allowed_users": {"type": "keyword"},
                "allowed_groups": {"type": "keyword"},
                "created_time": {"type": "date"},
                "modified_time": {"type": "date"},
                "indexed_time": {"type": "date"},
                "metadata": {"type": "object"},
            }
        },
    }
