# OpenRAG Backend Test Suite

Comprehensive test suite for the OpenRAG backend using pytest with fixtures (no mocks).

## Test Structure

The test suite is organized to mirror the source code structure:

```
tests/
├── api/                    # API endpoint tests
│   ├── test_documents.py
│   ├── test_health.py
│   └── test_search.py
├── services/              # Service layer tests
│   ├── test_document_service.py
│   └── test_search_service.py
├── connectors/            # Connector tests
│   └── test_base.py
├── utils/                 # Utility function tests
│   ├── test_embeddings.py
│   └── test_hash_utils.py
├── config/                # Configuration tests
│   └── test_settings.py
├── models/                # Model tests
├── fixtures/              # Shared test fixtures
│   ├── opensearch_fixtures.py
│   ├── service_fixtures.py
│   ├── connector_fixtures.py
│   └── app_fixtures.py
└── conftest.py            # Root pytest configuration
```

## Running Tests

### Quick Start

```bash
# Run all tests
make test

# Run only unit tests (fastest)
make test-unit

# Run with coverage report
make test-coverage
```

### Detailed Commands

```bash
# Run all tests
uv run pytest

# Run unit tests only
uv run pytest -m unit

# Run integration tests only
uv run pytest -m integration

# Run specific test categories
uv run pytest -m api        # API tests
uv run pytest -m service    # Service tests
uv run pytest -m connector  # Connector tests

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/utils/test_embeddings.py

# Run specific test function
uv run pytest tests/utils/test_embeddings.py::TestEmbeddingDimensions::test_get_openai_embedding_dimensions

# Run with coverage
uv run pytest --cov=src --cov-report=html

# Re-run only failed tests
uv run pytest --lf

# Run tests in parallel (requires pytest-xdist)
uv run pytest -n auto
```

## Test Markers

Tests are organized using pytest markers:

- `@pytest.mark.unit` - Unit tests (fast, no external dependencies)
- `@pytest.mark.integration` - Integration tests (require external services)
- `@pytest.mark.api` - API endpoint tests
- `@pytest.mark.service` - Service layer tests
- `@pytest.mark.connector` - Connector tests
- `@pytest.mark.requires_opensearch` - Tests requiring OpenSearch
- `@pytest.mark.requires_langflow` - Tests requiring Langflow
- `@pytest.mark.slow` - Slow running tests

## Fixtures

### Global Fixtures (conftest.py)

Available to all tests:

- `temp_dir` - Temporary directory for test files
- `test_file` - Sample test file
- `sample_document_data` - Sample document data
- `sample_user_data` - Sample user data
- `sample_jwt_token` - Sample JWT token
- `auth_headers` - Authentication headers
- `sample_flow_data` - Sample Langflow flow data
- `sample_chat_message` - Sample chat message
- `sample_conversation_data` - Sample conversation history
- `sample_connector_config` - Sample connector configuration
- `sample_search_query` - Sample search query
- `sample_embedding_vector` - Sample embedding vector
- `test_documents_batch` - Batch of test documents
- `test_env_vars` - Test environment variables
- `mock_opensearch_response` - Mock OpenSearch response
- `mock_langflow_response` - Mock Langflow response

### OpenSearch Fixtures

From `fixtures/opensearch_fixtures.py`:

- `opensearch_client` - Real OpenSearch client (requires OpenSearch running)
- `opensearch_test_index` - Test index with automatic cleanup
- `populated_opensearch_index` - Pre-populated test index
- `opensearch_document_mapping` - Document index mapping
- `opensearch_knowledge_filter_mapping` - Knowledge filter mapping

### Service Fixtures

From `fixtures/service_fixtures.py`:

- `document_service` - DocumentService instance
- `search_service` - SearchService instance
- `auth_service` - AuthService instance
- `chat_service` - ChatService instance
- `knowledge_filter_service` - KnowledgeFilterService instance
- `flows_service` - FlowsService instance
- `models_service` - ModelsService instance
- `task_service` - TaskService instance
- And more...

### Connector Fixtures

From `fixtures/connector_fixtures.py`:

- `google_drive_connector` - GoogleDriveConnector instance
- `onedrive_connector` - OneDriveConnector instance
- `sharepoint_connector` - SharePointConnector instance
- `connection_manager` - ConnectionManager instance
- `sample_google_drive_file` - Sample Google Drive file metadata
- `sample_onedrive_item` - Sample OneDrive item metadata
- `sample_sharepoint_item` - Sample SharePoint item metadata

## Writing Tests

### Unit Test Example

```python
import pytest

@pytest.mark.unit
class TestMyFeature:
    """Test suite for my feature."""

    def test_basic_functionality(self, sample_document_data):
        """Test basic functionality."""
        # Arrange
        doc = sample_document_data

        # Act
        result = process_document(doc)

        # Assert
        assert result is not None
        assert result["status"] == "success"
```

### Integration Test Example

```python
import pytest

@pytest.mark.integration
@pytest.mark.requires_opensearch
class TestDocumentIndexing:
    """Integration tests for document indexing."""

    @pytest.mark.asyncio
    async def test_document_indexing(
        self,
        opensearch_client,
        opensearch_test_index,
        sample_document_data
    ):
        """Test document indexing workflow."""
        # Index document
        await opensearch_client.index(
            index=opensearch_test_index,
            id=sample_document_data["id"],
            body=sample_document_data,
            refresh=True,
        )

        # Verify
        result = await opensearch_client.get(
            index=opensearch_test_index,
            id=sample_document_data["id"]
        )

        assert result["found"]
        assert result["_source"]["filename"] == sample_document_data["filename"]
```

### Async Test Example

```python
import pytest

@pytest.mark.asyncio
async def test_async_operation(opensearch_client):
    """Test async operation."""
    result = await opensearch_client.search(
        index="test_index",
        body={"query": {"match_all": {}}}
    )

    assert "hits" in result
```

## Test Coverage

Current coverage target: 20% (will increase as more tests are added)

View coverage report:

```bash
# Generate HTML coverage report
make test-coverage

# Open in browser
open htmlcov/index.html
```

## Integration Tests

Integration tests require external services to be running:

```bash
# Start infrastructure (OpenSearch, Langflow)
make infra

# Run integration tests
uv run pytest -m integration

# Or run without integration tests
uv run pytest -m "not requires_opensearch and not requires_langflow"
```

## Best Practices

1. **Use Fixtures, Not Mocks**: Prefer real fixtures over mocks for better integration testing
2. **Organize by Category**: Use markers to organize tests by category
3. **Keep Tests Fast**: Unit tests should run quickly; use markers for slow tests
4. **Clean Up Resources**: Use fixtures with proper cleanup (yield pattern)
5. **Test One Thing**: Each test should test a single behavior
6. **Use Descriptive Names**: Test names should describe what they test
7. **Follow AAA Pattern**: Arrange, Act, Assert
8. **Avoid Test Interdependence**: Tests should be independent
9. **Use Parametrize**: Use `@pytest.mark.parametrize` for similar tests with different inputs

## Continuous Integration

Tests are designed to run in CI environments:

```yaml
# Example GitHub Actions
- name: Run tests
  run: |
    make install-be
    make test-unit
```

## Troubleshooting

### Tests Fail with Import Errors

Make sure dependencies are installed:

```bash
uv sync --extra dev
```

### OpenSearch Connection Errors

Ensure OpenSearch is running:

```bash
make infra
```

### Slow Tests

Run only unit tests:

```bash
make test-unit
```

Or skip slow tests:

```bash
uv run pytest -m "not slow"
```

## Adding New Tests

1. Create test file in appropriate directory
2. Follow naming convention: `test_*.py`
3. Use appropriate markers
4. Add fixtures to `fixtures/` if reusable
5. Update this README if adding new test categories

## Test Statistics

- Total Tests: 77+ unit tests, 20+ integration tests
- Unit Test Runtime: ~2 seconds
- Integration Test Runtime: ~10 seconds (with OpenSearch)
- Code Coverage: Growing (target 70%+)
