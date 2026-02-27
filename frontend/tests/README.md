# Testing

This directory and its subdirectories generally contain tests for the application.

## End-to-End (E2E) Tests

The E2E tests for the frontend are written using Playwright and are located in the `frontend/tests` or configured to run from the `frontend` directory.

### Running E2E Tests Locally

To run the Playwright E2E tests locally, follow these steps:

#### 1. Setup Infrastructure
The E2E tests require the backend infrastructure (database, API, etc.) to be running.
We provide a setup script that automates the process of creating a test environment, managing environment variables, and starting the required containers:

```bash
./scripts/setup-e2e.sh
```

**What this script does:**
- Copies `frontend/.env.test.example` to `frontend/.env.test` if it doesn't already exist.
- Auto-generates any required missing secrets (e.g., `OPENSEARCH_PASSWORD`) in the `.env.test` file.
- Performs a factory reset to clear old data (using `make factory-reset`).
- Starts the infrastructure using `make dev-local-cpu` with the new `.env.test` file.
- Waits for services like OpenSearch and the Langflow backend to become healthy before proceeding.

**Alternative: Manual Setup**
If you prefer not to use the automated setup script, you can manually start the infrastructure:
1. Ensure that `frontend/.env.test` is created and configured correctly (e.g., `OPENSEARCH_PASSWORD` must be set).
2. Clean up old data by running: `make factory-reset ENV_FILE=frontend/.env.test`
3. Start the infrastructure by running: `make dev-local-cpu ENV_FILE=frontend/.env.test`

#### 2. Run Playwright Tests
Once the infrastructure is up and running, you can execute the Playwright tests.
Navigate to the `frontend` directory and run the tests:

```bash
cd frontend
npx playwright test
```

*Note: You may need to run `npx playwright install` first to download the required browsers if you haven't already.*

### Teardown

After running the tests, you can shut down and clean up the test infrastructure using Docker Compose. Ensure you use the same environment file:

```bash
docker compose --env-file frontend/.env.test down -v --remove-orphans
```
