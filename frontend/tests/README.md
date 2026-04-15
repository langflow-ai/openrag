# Testing

This directory and its subdirectories generally contain tests for the application.

## End-to-End (E2E) Tests

The E2E tests for the frontend are written using Playwright and are located in the `frontend/tests` or configured to run from the `frontend` directory.

### Running E2E Tests Locally

To run the Playwright E2E tests locally, follow these steps:

#### 1. Setup Infrastructure
The E2E tests require the full stack (database, API, frontend, etc.) to be running.
We provide a setup script that automates the process of starting the full stack and waiting for all services to be ready:

```bash
./scripts/setup-e2e.sh
```

**What this script does:**
- Pre-creates required directories (e.g., `langflow-data`).
- Starts the full stack using `make dev-cpu`.
- Starts the docling service using `make docling`.
- Waits for services (OpenSearch, Langflow, and Frontend) to become healthy before proceeding.

**Note:** This script uses your standard root `.env` file configuration. Specialized `.env.test` files are no longer required.

**Alternative: Manual Setup**
If you prefer not to use the automated setup script, you can manually start the infrastructure:
1. Ensure your root `.env` is configured correctly.
2. Start the services: `make dev-cpu`
3. Start docling: `make docling`
4. Wait for all services to be healthy: `make health`

#### 2. Run Playwright Tests
Once the infrastructure is up and running, you can execute the Playwright tests.
Navigate to the `frontend` directory and run the tests:

```bash
cd frontend
npx playwright test
```

*Note: You may need to run `npx playwright install` first to download the required browsers if you haven't already.*
*The Playwright configuration is set to reuse existing servers on ports 8000 (Backend) and 3000 (Frontend) if they are already running.*

### Teardown

After running the tests, you can shut down and clean up the test infrastructure using the Makefile:

```bash
make clean
```
