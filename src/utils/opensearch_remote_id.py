"""OpenSearch ``remote_id`` field: mapping ensure + backfill for connector sync."""

from __future__ import annotations

from utils.logging_config import get_logger

logger = get_logger(__name__)

REMOTE_ID_MAPPING = {"properties": {"remote_id": {"type": "keyword"}}}

# Content-hash document_ids from hash_id() are 24-char base64url digests; connector
# source item ids (SharePoint, Drive, etc.) are typically longer.
BACKFILL_REMOTE_ID_SCRIPT = """
if (ctx._source.connector_type == null || ctx._source.connector_type == 'local') {
  return;
}
if (ctx._source.remote_id != null && ctx._source.remote_id != '') {
  return;
}
if (ctx._source.document_id == null || ctx._source.document_id == '') {
  return;
}
String docId = ctx._source.document_id;
if (docId.length() == 24) {
  return;
}
ctx._source.remote_id = docId;
"""


async def ensure_remote_id_mapping(opensearch_client, index_name: str) -> None:
    """Add ``remote_id`` keyword mapping when the index already exists."""
    try:
        await opensearch_client.indices.put_mapping(
            index=index_name,
            body=REMOTE_ID_MAPPING,
        )
        logger.info("Ensured remote_id mapping", index_name=index_name)
    except Exception as e:
        logger.warning(
            "Failed to ensure remote_id mapping (may already exist)",
            index_name=index_name,
            error=str(e),
        )


async def backfill_remote_id(opensearch_client, index_name: str) -> None:
    """Populate ``remote_id`` on legacy connector chunks where ``document_id`` is the source item id.

    Skips local uploads and rows whose ``document_id`` is a content hash (standard ingest path).
    """
    try:
        result = await opensearch_client.update_by_query(
            index=index_name,
            body={
                "query": {
                    "bool": {
                        "must": [
                            {"exists": {"field": "connector_type"}},
                        ],
                        "must_not": [
                            {"term": {"connector_type": "local"}},
                        ],
                        "should": [
                            {"bool": {"must_not": {"exists": {"field": "remote_id"}}}},
                            {"term": {"remote_id": ""}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "script": {
                    "source": BACKFILL_REMOTE_ID_SCRIPT,
                    "lang": "painless",
                },
            },
            conflicts="proceed",
            refresh=False,
        )
        updated = result.get("updated", 0)
        if updated:
            logger.info(
                "Backfilled remote_id on connector chunks",
                index_name=index_name,
                updated=updated,
            )
    except Exception as e:
        logger.warning(
            "remote_id backfill skipped or failed",
            index_name=index_name,
            error=str(e),
        )
