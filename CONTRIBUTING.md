# Contributing to OpenRAG

Welcome to OpenRAG! This guide will help you set up your development environment and start contributing quickly.

## Quick Start (5 Minutes)

Get OpenRAG running in three commands:

```bash
make check_tools  # Verify you have all prerequisites
make setup        # Install dependencies and create .env
make dev          # Start OpenRAG
```

That's it! OpenRAG is now running at:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
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

### Verify Prerequisites

```bash
make check_tools
```

You should see: `All required tools are installed.`

---

## Initial Setup

### 1. Clone and Setup

```bash
git clone https://github.com/langflow-ai/openrag.git
cd openrag
make setup
```

### 2. Configure Environment

Edit the `.env` file with your credentials:

```bash
# Required
OPENAI_API_KEY=your_openai_api_key
OPENSEARCH_PASSWORD=your_secure_password
LANGFLOW_SUPERUSER=admin
LANGFLOW_SUPERUSER_PASSWORD=your_secure_password
```

For all configuration options, see [docs/reference/configuration.mdx](docs/docs/reference/configuration.mdx).

### 3. Start OpenRAG

```bash
make dev      # With GPU support
# or
make dev-cpu  # CPU only
```

---

## Development Workflows

Choose the workflow that fits your needs:

### A) Full Docker Stack (Simplest)

Everything runs in containers. Best for testing the full system.

```bash
make dev          # Start with GPU support
make dev-cpu      # Start with CPU only
make stop         # Stop and remove all containers
```

### B) Local Development (Recommended for Development)

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

```bash
make factory-reset  # Complete reset: containers, volumes, and data
```

---

## Makefile Help System

The Makefile provides organized help for all commands:

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

Ensure these ports are available:
- 3000 (Frontend)
- 7860 (Langflow)
- 8000 (Backend)
- 9200 (OpenSearch)
- 5601 (OpenSearch Dashboards)

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

If things aren't working, try a full reset:

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

## Pull Request Guidelines

1. **Fork and Branch**: Create a feature branch from `main`
2. **Test**: Ensure tests pass with `make test` and `make lint`
3. **Document**: Update relevant documentation
4. **Commit**: Use clear, descriptive commit messages
5. **PR Description**: Explain changes and include testing instructions

---

## Getting Help

- Run `make help` to see all available commands
- Check existing [issues](https://github.com/langflow-ai/openrag/issues)
- Review [documentation](docs/)
- Use `make status` and `make health` for debugging
- View logs with `make logs`

Thank you for contributing to OpenRAG!
