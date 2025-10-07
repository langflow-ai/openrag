"""
OpenSearch fixtures for testing.
These fixtures provide real or test OpenSearch clients and test data.
"""

import pytest
from opensearchpy import AsyncOpenSearch
from typing import AsyncGenerator


@pytest.fixture
async def opensearch_client() -> AsyncGenerator[AsyncOpenSearch, None]:
    """
    Provide a real OpenSearch client for integration tests.
    This connects to the actual OpenSearch instance running in Docker.
    """
    client = AsyncOpenSearch(
        hosts=[{"host": "localhost", "port": 9200}],
        http_auth=("admin", "admin"),
        use_ssl=True,
        verify_certs=False,
        ssl_show_warn=False,
    )

    yield client

    await client.close()


@pytest.fixture
async def opensearch_test_index(opensearch_client: AsyncOpenSearch) -> AsyncGenerator[str, None]:
    """
    Create a test index in OpenSearch and clean it up after the test.
    """
    index_name = "test_documents"

    # Create index
    if await opensearch_client.indices.exists(index=index_name):
        await opensearch_client.indices.delete(index=index_name)

    await opensearch_client.indices.create(
        index=index_name,
        body={
            "mappings": {
                "properties": {
                    "filename": {"type": "text"},
                    "content": {"type": "text"},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": 768,
                    },
                    "metadata": {"type": "object"},
                    "created_at": {"type": "date"},
                }
            }
        },
    )

    yield index_name

    # Cleanup
    if await opensearch_client.indices.exists(index=index_name):
        await opensearch_client.indices.delete(index=index_name)


@pytest.fixture
async def populated_opensearch_index(
    opensearch_client: AsyncOpenSearch,
    opensearch_test_index: str,
    test_documents_batch: list,
) -> str:
    """
    Create and populate a test index with sample documents.
    """
    # Index documents
    for doc in test_documents_batch:
        await opensearch_client.index(
            index=opensearch_test_index,
            id=doc["id"],
            body=doc,
            refresh=True,
        )

    return opensearch_test_index


@pytest.fixture
def opensearch_document_mapping() -> dict:
    """Provide the document index mapping schema."""
    return {
        "mappings": {
            "properties": {
                "filename": {"type": "text"},
                "filepath": {"type": "keyword"},
                "content": {"type": "text"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": 768,
                },
                "metadata": {
                    "properties": {
                        "source": {"type": "keyword"},
                        "uploaded_by": {"type": "keyword"},
                        "file_size": {"type": "long"},
                        "mime_type": {"type": "keyword"},
                        "created_at": {"type": "date"},
                        "updated_at": {"type": "date"},
                    }
                },
                "chunks": {
                    "type": "nested",
                    "properties": {
                        "text": {"type": "text"},
                        "embedding": {
                            "type": "knn_vector",
                            "dimension": 768,
                        },
                        "chunk_index": {"type": "integer"},
                    },
                },
            }
        }
    }


@pytest.fixture
def opensearch_knowledge_filter_mapping() -> dict:
    """Provide the knowledge filter index mapping schema."""
    return {
        "mappings": {
            "properties": {
                "name": {"type": "text"},
                "description": {"type": "text"},
                "query": {"type": "text"},
                "document_ids": {"type": "keyword"},
                "created_by": {"type": "keyword"},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
            }
        }
    }
