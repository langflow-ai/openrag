# Contributing to OpenRAG

![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)
![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.13+-blue.svg)
![Node.js](https://img.shields.io/badge/node.js-18+-green.svg)

**Thank you for your interest in contributing to OpenRAG!** 🎉

Whether you're fixing a bug, adding a feature, improving documentation, or just exploring — every contribution matters and helps make OpenRAG better for everyone.

This guide will help you set up your development environment and start contributing quickly.

## Table of Contents

- [Quickstart](#quickstart)
- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
- [Development Workflows](#development-workflows)
- [Service Management](#service-management)
- [Reset & Cleanup](#reset--cleanup)
- [Makefile Help System](#makefile-help-system)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Code Style](#code-style)
- [Create a Pull Request](#create-a-pull-request)

---

## Quickstart

Get OpenRAG running in three commands:

```bash
make check_tools  # Verify you have all prerequisites
make setup        # Install dependencies and create .env
make dev          # Start OpenRAG
```

OpenRAG is now running locally on the following ports:

- **Frontend**: http://localhost:3000
- **Langflow**: http://localhost:7860

---

## Prerequisites

### Required Tools

| Tool | Version | Installation |
|------|---------|--------------|
| Docker or Podman | Latest | [Docker](https://docs.docker.com/get-docker/) or [Podman](https://podman.io/getting-started/installation) |
| Python | 3.13+ | With [uv](https://github.com/astral-sh/uv) package manager |
| Node.js | 18+ | With npm |
| Make | Any | Usually pre-installed on macOS/Linux |

### Podman Setup (macOS)

If using Podman on macOS, configure the VM with enough memory (8GB recommended):

```bash
# Stop and remove existing machine (if any)
podman machine stop
podman machine rm

# Create new machine with 8GB RAM and 4 CPUs
podman machine init --memory 8192 --cpus 4
podman machine start
```

> [!IMPORTANT]
> 8GB RAM is the minimum recommended for running OpenRAG smoothly. If you experience crashes or slowness, increase the memory allocation.

### Verify Prerequisites

```bash
make check_tools
```

You should see: `All required tools are installed.`

---

## Initial Setup


1. Clone the repo and setup the project:

   ```bash
   git clone https://github.com/langflow-ai/openrag.git
   cd openrag
   make setup
   ```

2. Configure the required environment variables before starting OpenRAG:

   ```env
   OPENAI_API_KEY=
   OPENSEARCH_PASSWORD=
   LANGFLOW_SUPERUSER=admin
   LANGFLOW_SUPERUSER_PASSWORD=
   ```

   The `OPENSEARCH_PASSWORD` must adhere to the [OpenSearch password complexity requirements](https://docs.opensearch.org/latest/security/configuration/demo-configuration/#setting-up-a-custom-admin-password).

   If `LANGFLOW_SUPERUSER_PASSWORD` isn't set, then the Langflow instance starts without authentication enabled.

   For more information, see the [OpenRAG environment variables reference](https://docs.openr.ag/reference/configuration).

3. Start OpenRAG using one of the options described in the next section.
    ```bash
    make dev      # With GPU support
    # or
    make dev-cpu  # CPU only
    ```

---

## Development Workflows

There are multiple ways to start OpenRAG based on your use case:

* Local development environment: Recommended for development.
* Full Docker stack: Simple build that runs everything in containers. Not ideal for development. Best for testing the full system.
* Branch development: Build OpenRAG with a fork or branch of the [Langflow repository](https://github.com/langflow-ai/langflow).
* Docling only: Run the Docling service by itself.

### Full Docker Stack (Simplest)

Everything runs in containers. Best for testing the full system.

```bash
make dev          # Start with GPU support
make dev-cpu      # Start with CPU only
make stop         # Stop and remove all containers
```

### B) Local Development (Recommended for Development)

> [!TIP]
> This is the **recommended workflow** for active development. It provides faster code reloading and easier debugging.

Run infrastructure in Docker, but backend/frontend locally for faster iteration.

```bash
# Terminal 1: Start infrastructure (OpenSearch, Langflow, Dashboards)
make dev-local

# Terminal 2: Run backend locally
make backend

# Terminal 3: Run frontend locally
make frontend

# Terminal 4 (optional): Start docling for document processing
make docling
```

**Benefits:**
- Faster code reloading
- Direct access to logs and debugging
- Easier testing and iteration

### C) Branch Development (Custom Langflow)

Build and run OpenRAG with a custom Langflow branch:

```bash
# Use a specific branch
make dev-branch BRANCH=my-feature-branch

# Use a different repository
make dev-branch BRANCH=feature-x REPO=https://github.com/myorg/langflow.git
```

> [!NOTE]
> The first build may take several minutes as it compiles Langflow from source.

**Additional branch commands:**
```bash
make build-langflow-dev  # Rebuild Langflow image (no cache)
make stop-dev            # Stop branch dev containers
make restart-dev         # Restart branch dev environment
make clean-dev           # Clean branch dev containers and volumes
make logs-lf-dev         # View Langflow dev logs
make shell-lf-dev        # Shell into Langflow dev container
```

### D) Docling Service (Document Processing)

Docling handles document parsing and OCR:

```bash
make docling       # Start docling-serve
make docling-stop  # Stop docling-serve
```

---

## Service Management

### Stop All Services

```bash
make stop  # Stops and removes all OpenRAG containers
```

### Check Status

```bash
make status  # Show container status
make health  # Check health of all services
```

### View Logs

```bash
make logs     # All container logs
make logs-be  # Backend logs only
make logs-fe  # Frontend logs only
make logs-lf  # Langflow logs only
make logs-os  # OpenSearch logs only
```

### Shell Access

```bash
make shell-be  # Shell into backend container
make shell-lf  # Shell into Langflow container
make shell-os  # Shell into OpenSearch container
```

---

## Reset & Cleanup

### Stop and Clean Containers

```bash
make stop   # Stop and remove containers
make clean  # Stop, remove containers, and delete volumes
```

### Reset Database

```bash
make db-reset       # Reset OpenSearch indices (keeps data directory)
make clear-os-data  # Clear OpenSearch data directory completely
```

### Full Factory Reset

> [!CAUTION]
> This will delete all data, containers, and volumes. Use only when you need a completely fresh start.

```bash
make factory-reset  # Complete reset: containers, volumes, and data
```

---

## Makefile Help System

> [!TIP]
> The Makefile provides color-coded, organized help for all commands. Run `make help` to get started!

```bash
make help         # Main help with common commands
make help_dev     # Development environment commands
make help_docker  # Docker and container commands
make help_test    # Testing commands
make help_local   # Local development commands
make help_utils   # Utility commands (logs, cleanup, etc.)
```

---

## Testing

### Run Tests

```bash
make test              # Run all backend tests
make test-integration  # Run integration tests (requires infra)
make test-sdk          # Run SDK tests (requires running OpenRAG)
make lint              # Run linting checks
```

### CI Tests

```bash
make test-ci        # Full CI: start infra, run tests, tear down
make test-ci-local  # Same as above, but builds images locally
```

---

## Project Structure

```
openrag/
├── src/                    # Backend Python code
│   ├── api/               # REST API endpoints
│   ├── services/          # Business logic
│   ├── models/            # Data models
│   ├── connectors/        # External integrations
│   └── config/            # Configuration
├── frontend/              # Next.js frontend
│   ├── app/              # App router pages
│   ├── components/       # React components
│   └── contexts/         # State management
├── flows/                 # Langflow flow definitions
├── docs/                  # Documentation
├── tests/                 # Test files
├── Makefile              # Development commands
└── docker-compose.yml    # Container orchestration
```

---

## Troubleshooting

### Port Conflicts

> [!NOTE]
> Ensure these ports are available before starting OpenRAG:

| Port | Service |
|------|---------|
| 3000 | Frontend |
| 7860 | Langflow |
| 8000 | Backend |
| 9200 | OpenSearch |
| 5601 | OpenSearch Dashboards |

### Memory Issues

If containers crash or are slow:

```bash
# For Podman on macOS, increase VM memory
podman machine stop
podman machine rm
podman machine init --memory 8192 --cpus 4
podman machine start
```

### Environment Reset

> [!TIP]
> If things aren't working, try a full reset:

```bash
make stop
make clean
cp .env.example .env  # Reconfigure as needed
make setup
make dev
```

### Check Service Health

```bash
make health
```

### Need More Help?

- Run `make help` to see all available commands
- Check existing [issues](https://github.com/langflow-ai/openrag/issues)
- Review [documentation](docs/)
- Use `make status` and `make health` for debugging
- View logs with `make logs`

---

## Code Style

### Backend (Python)
- Follow PEP 8 style guidelines
- Use type hints
- Document with docstrings
- Use `structlog` for logging

### Frontend (TypeScript/React)
- Follow React/Next.js best practices
- Use TypeScript for type safety
- Use Tailwind CSS for styling
- Follow established component patterns

---

## Create a Pull Request

If you want to propose your changes to the OpenRAG maintainers, make sure your code is fully tested and ready for review:

1. **Fork and Branch**: Create a feature branch from `main`
2. **Test**: Ensure tests pass with `make test` and `make lint`
3. **Document**: Update relevant documentation.
To build and test documentation changes, see [Contribute OpenRAG documentation](https://docs.openr.ag/support/contribute#contribute-documentation).
4. **Commit**: Use clear, descriptive commit messages
5. **PR Description**: Explain changes and include testing instructions

> [!IMPORTANT]
> All PRs must pass CI tests before merging.

For more information and suggestions for successful contributions, see [Contribute to OpenRAG](https://docs.openr.ag/support/contribute#contribute-to-the-codebase).


Thank you for contributing to OpenRAG! 🚀
