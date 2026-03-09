#!/usr/bin/env python3
"""
Migration script to migrate legacy embeddings to multi-model setup.

This script migrates documents from the legacy single-field embedding system
to the new multi-model system with dynamic field names.

Legacy format:
    {
        "chunk_embedding": [0.1, 0.2, ...],
        // no embedding_model field
    }

New format:
    {
        "chunk_embedding_text_embedding_3_small": [0.1, 0.2, ...],
        "embedding_model": "text-embedding-3-small"
    }

Usage:
    uv run python scripts/migrate_embedding_model_field.py --model <model_name>

Example:
    uv run python scripts/migrate_embedding_model_field.py --model text-embedding-3-small

Options:
    --model MODEL       The embedding model name to assign to legacy embeddings
                       (e.g., "text-embedding-3-small", "nomic-embed-text")
    --batch-size SIZE   Number of documents to process per batch (default: 100)
    --dry-run          Show what would be migrated without making changes
    --index INDEX      Index name (default: documents)

What it does:
    1. Finds all documents with legacy "chunk_embedding" field but no "embedding_model" field
    2. For each document:
       - Copies the vector from "chunk_embedding" to "chunk_embedding_{model_name}"
       - Adds "embedding_model" field with the specified model name
       - Optionally removes the legacy "chunk_embedding" field
    3. Uses bulk updates for efficiency

Note: This script does NOT re-embed documents. It simply tags existing embeddings
with the model name you specify. Make sure to specify the correct model that was
actually used to create those embeddings.
"""
import asyncio
import sys
import os
import argparse
from typing import List, Dict, Any

from opensearchpy import AsyncOpenSearch, helpers
from opensearchpy._async.http_aiohttp import AIOHttpConnection

# Add src directory to path to import config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from config.settings import (
    KNN_EF_CONSTRUCTION,
    KNN_M,
    OPENSEARCH_HOST,
    OPENSEARCH_PORT,
    OPENSEARCH_USERNAME,
    OPENSEARCH_PASSWORD,
    get_index_name,
)
from utils.logging_config import get_logger
from utils.embedding_fields import get_embedding_field_name

logger = get_logger(__name__)


async def ensure_new_field_exists(
    client: AsyncOpenSearch,
    index_name: str,
    field_name: str,
    dimensions: int
) -> None:
    """Ensure the new embedding field exists in the index."""
    mapping = {
        "properties": {
            field_name: {
                "type": "knn_vector",
                "dimension": dimensions,
                "method": {
                    "name": "disk_ann",
                    "engine": "jvector",
                    "space_type": "l2",
                    "parameters": {"ef_construction": KNN_EF_CONSTRUCTION, "m": KNN_M},
                },
            },
            "embedding_model": {
                "type": "keyword"
            }
        }
    }

    try:
        await client.indices.put_mapping(index=index_name, body=mapping)
        logger.info(f"Ensured field exists: {field_name}")
    except Exception as e:
        error_msg = str(e).lower()
        if "already" in error_msg or "exists" in error_msg:
            logger.debug(f"Field already exists: {field_name}")
        else:
            logger.error(f"Failed to add field mapping: {e}")
            raise


async def find_legacy_documents(
    client: AsyncOpenSearch,
    index_name: str,
    batch_size: int = 100
) -> List[Dict[str, Any]]:
    """Find all documents with legacy chunk_embedding but no embedding_model field."""
    query = {
        "query": {
            "bool": {
                "must": [
                    {"exists": {"field": "chunk_embedding"}}
                ],
                "must_not": [
                    {"exists": {"field": "embedding_model"}}
                ]
            }
        },
        "size": batch_size,
        "_source": True
    }

    try:
        response = await client.search(index=index_name, body=query, scroll='5m')
        scroll_id = response['_scroll_id']
        hits = response['hits']['hits']

        all_docs = hits

        # Continue scrolling until no more results
        while len(hits) > 0:
            response = await client.scroll(scroll_id=scroll_id, scroll='5m')
            scroll_id = response['_scroll_id']
            hits = response['hits']['hits']
            all_docs.extend(hits)

        # Clean up scroll
        await client.clear_scroll(scroll_id=scroll_id)

        return all_docs
    except Exception as e:
        logger.error(f"Error finding legacy documents: {e}")
        raise


async def migrate_documents(
    client: AsyncOpenSearch,
    index_name: str,
    documents: List[Dict[str, Any]],
    model_name: str,
    new_field_name: str,
    dry_run: bool = False
) -> Dict[str, int]:
    """Migrate legacy documents to new format."""
    if not documents:
        return {"migrated": 0, "errors": 0}

    if dry_run:
        logger.info(f"DRY RUN: Would migrate {len(documents)} documents")
        for doc in documents[:5]:  # Show first 5 as sample
            doc_id = doc['_id']
            has_legacy = 'chunk_embedding' in doc['_source']
            logger.info(f"  Document {doc_id}: has_legacy={has_legacy}")
        if len(documents) > 5:
            logger.info(f"  ... and {len(documents) - 5} more documents")
        return {"migrated": len(documents), "errors": 0}

    # Prepare bulk update actions
    actions = []
    for doc in documents:
        doc_id = doc['_id']
        source = doc['_source']

        # Copy the legacy embedding to the new field
        legacy_embedding = source.get('chunk_embedding')
        if not legacy_embedding:
            logger.warning(f"Document {doc_id} missing chunk_embedding, skipping")
            continue

        # Build update document
        update_doc = {
            new_field_name: legacy_embedding,
            "embedding_model": model_name
        }

        action = {
            "_op_type": "update",
            "_index": index_name,
            "_id": doc_id,
            "doc": update_doc
        }
        actions.append(action)

    # Execute bulk update
    migrated = 0
    errors = 0

    try:
        success, failed = await helpers.async_bulk(
            client,
            actions,
            raise_on_error=False,
            raise_on_exception=False
        )
        migrated = success
        errors = len(failed) if isinstance(failed, list) else 0

        if errors > 0:
            logger.error(f"Failed to migrate {errors} documents")
            for failure in (failed if isinstance(failed, list) else [])[:5]:
                logger.error(f"  Error: {failure}")

        logger.info(f"Successfully migrated {migrated} documents")
    except Exception as e:
        logger.error(f"Bulk migration failed: {e}")
        raise

    return {"migrated": migrated, "errors": errors}


async def migrate_legacy_embeddings(
    model_name: str,
    batch_size: int = 100,
    dry_run: bool = False,
    index_name: str = None
) -> bool:
    """Main migration function."""
    if index_name is None:
        index_name = get_index_name()

    new_field_name = get_embedding_field_name(model_name)

    logger.info("=" * 60)
    logger.info("Legacy Embedding Migration")
    logger.info("=" * 60)
    logger.info(f"Index: {index_name}")
    logger.info(f"Model: {model_name}")
    logger.info(f"New field: {new_field_name}")
    logger.info(f"Batch size: {batch_size}")
    logger.info(f"Dry run: {dry_run}")
    logger.info("=" * 60)

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
        exists = await client.indices.exists(index=index_name)
        if not exists:
            logger.error(f"Index '{index_name}' does not exist")
            return False

        # Find legacy documents
        logger.info("Searching for legacy documents...")
        legacy_docs = await find_legacy_documents(client, index_name, batch_size)

        if not legacy_docs:
            logger.info("No legacy documents found. Migration not needed.")
            return True

        logger.info(f"Found {len(legacy_docs)} legacy documents to migrate")

        # Get vector dimension from first document
        first_doc = legacy_docs[0]
        legacy_embedding = first_doc['_source'].get('chunk_embedding', [])
        dimensions = len(legacy_embedding)
        logger.info(f"Detected vector dimensions: {dimensions}")

        # Ensure new field exists
        if not dry_run:
            logger.info(f"Ensuring new field exists: {new_field_name}")
            await ensure_new_field_exists(client, index_name, new_field_name, dimensions)

        # Migrate documents
        logger.info("Starting migration...")
        result = await migrate_documents(
            client,
            index_name,
            legacy_docs,
            model_name,
            new_field_name,
            dry_run
        )

        logger.info("=" * 60)
        logger.info("Migration Summary")
        logger.info("=" * 60)
        logger.info(f"Total documents: {len(legacy_docs)}")
        logger.info(f"Successfully migrated: {result['migrated']}")
        logger.info(f"Errors: {result['errors']}")
        logger.info("=" * 60)

        if result['errors'] > 0:
            logger.warning("Migration completed with errors")
            return False

        if dry_run:
            logger.info("DRY RUN completed. No changes were made.")
            logger.info(f"Run without --dry-run to perform the migration")
        else:
            logger.info("Migration completed successfully!")

        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(
        description="Migrate legacy embeddings to multi-model setup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would be migrated
  uv run python scripts/migrate_embedding_model_field.py --model text-embedding-3-small --dry-run

  # Perform actual migration
  uv run python scripts/migrate_embedding_model_field.py --model text-embedding-3-small

  # Migrate with custom batch size
  uv run python scripts/migrate_embedding_model_field.py --model nomic-embed-text --batch-size 500
        """
    )

    parser.add_argument(
        '--model',
        required=True,
        help='Embedding model name to assign to legacy embeddings (e.g., "text-embedding-3-small")'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Number of documents to process per batch (default: 100)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be migrated without making changes'
    )
    parser.add_argument(
        '--index',
        default=None,
        help=f'Index name (default: {get_index_name()})'
    )

    args = parser.parse_args()

    # Run migration
    success = asyncio.run(migrate_legacy_embeddings(
        model_name=args.model,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        index_name=args.index
    ))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
