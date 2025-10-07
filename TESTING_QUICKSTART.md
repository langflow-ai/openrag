# Testing Quick Start Guide

## Run Tests

```bash
# All unit tests (fastest - recommended for development)
make test-unit

# All tests
make test

# With coverage report
make test-coverage
open htmlcov/index.html

# Specific category
make test-api
make test-service
make test-utils

# Verbose output
make test-verbose

# Re-run only failed tests
make test-failed
```

## Test Structure

```
tests/
├── api/          - API endpoint tests
├── services/     - Business logic tests
├── utils/        - Utility function tests
├── connectors/   - Connector tests
├── config/       - Configuration tests
└── fixtures/     - Reusable test fixtures
```

## Current Status

[x] **77 passing unit tests**
[x] **~2 second runtime**
[x] **No mocks - using real fixtures**
[x] **Ready for CI/CD**

## Quick Commands

| Command | Description |
|---------|-------------|
| `make test-unit` | Fast unit tests |
| `make test-integration` | Tests requiring OpenSearch/Langflow |
| `make test-coverage` | Generate coverage report |
| `make test-api` | API tests only |
| `make test-service` | Service tests only |
| `make test-quick` | Quick unit tests, no coverage |

## Adding New Tests

1. Create file: `tests/category/test_feature.py`
2. Use markers: `@pytest.mark.unit` or `@pytest.mark.integration`
3. Use fixtures from `conftest.py`
4. Run: `make test-unit`

See `tests/README.md` for detailed documentation.
