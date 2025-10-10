#!/usr/bin/env python3
"""
Migration script to add embedding_model field to existing OpenSearch index.
Run this once to fix the field type from text to keyword.
"""
import asyncio
import sys
from opensearchpy import AsyncOpenSearch
from opensearchpy._async.http_aiohttp import AIOHttpConnection

# Add parent directory to path to import config
sys.path.insert(0, '/home/tato/Desktop/openrag/src')

from config.settings import (
    OPENSEARCH_HOST,
    OPENSEARCH_PORT,
    OPENSEARCH_USERNAME,
    OPENSEARCH_PASSWORD,
    INDEX_NAME,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def add_embedding_model_field():
    """Add embedding_model as keyword field to existing index"""

    # Create admin OpenSearch client
    client = AsyncOpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        connection_class=AIOHttpConnection,
        scheme="https",
        use_ssl=True,
        verify_certs=False,
        ssl_assert_fingerprint=None,
        http_auth=(OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD),
        http_compress=True,
    )

    try:
        # Check if index exists
        exists = await client.indices.exists(index=INDEX_NAME)
        if not exists:
            logger.error(f"Index {INDEX_NAME} does not exist")
            return False

        # Get current mapping
        mapping = await client.indices.get_mapping(index=INDEX_NAME)
        current_props = mapping[INDEX_NAME]["mappings"].get("properties", {})

        # Check if embedding_model field exists
        if "embedding_model" in current_props:
            current_type = current_props["embedding_model"].get("type")
            logger.info(f"embedding_model field exists with type: {current_type}")

            if current_type == "keyword":
                logger.info("Field is already correct type (keyword)")
                return True
            else:
                logger.warning(
                    f"Field exists with wrong type: {current_type}. "
                    "Cannot change field type on existing field. "
                    "You need to reindex or use a different field name."
                )
                return False

        # Add the field as keyword
        logger.info("Adding embedding_model field as keyword type")
        new_mapping = {
            "properties": {
                "embedding_model": {"type": "keyword"}
            }
        }

        response = await client.indices.put_mapping(
            index=INDEX_NAME,
            body=new_mapping
        )

        logger.info(f"Successfully added embedding_model field: {response}")

        # Verify the change
        updated_mapping = await client.indices.get_mapping(index=INDEX_NAME)
        updated_props = updated_mapping[INDEX_NAME]["mappings"]["properties"]

        if "embedding_model" in updated_props:
            field_type = updated_props["embedding_model"].get("type")
            logger.info(f"Verified: embedding_model field type is now: {field_type}")
            return field_type == "keyword"
        else:
            logger.error("Field was not added successfully")
            return False

    except Exception as e:
        logger.error(f"Error adding embedding_model field: {e}")
        return False
    finally:
        await client.close()


if __name__ == "__main__":
    success = asyncio.run(add_embedding_model_field())
    sys.exit(0 if success else 1)
