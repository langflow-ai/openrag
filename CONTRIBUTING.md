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
- [What's in this repo](#whats-in-this-repo)
- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
- [Development Workflows](#development-workflows)
- [Frequently Used `make` Commands](#frequently-used-make-commands)
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

For active development, run the infrastructure in containers and the backend and frontend from your checkout:

```bash
make check_tools  # Verify you have all prerequisites
make setup        # Install dependencies and create .env
# Populate the required values in .env, then:
make dev-local-cpu  # Start local development infrastructure
# In separate terminals: make backend, make frontend, and make docling
```

OpenRAG is then running locally on the following ports:

- **Frontend**: http://localhost:3000
- **Langflow**: http://localhost:7860

---

## What's in this repo

OpenRAG is a monorepo. Here's the shape of it and where to look depending on what you're changing:

| Component | Where | What it is |
|---|---|---|
| **Backend** | `src/` | A FastAPI (Python 3.13) service — REST API, RBAC/auth, connectors, document ingestion orchestration, and the built-in MCP server. Runs on port `8000`. |
| **Frontend** | `frontend/` | A Next.js (App Router, TypeScript, Tailwind) app — chat UI, document management, settings. Runs on port `3000` and proxies API/MCP calls to the backend. |
| **Langflow** | (pulled as a container, or built from source — see [Branch Development](#c-branch-development-custom-langflow)) | Powers the actual RAG flows: ingestion, retrieval, and agentic nudges. Runs on port `7860`. |
| **Python SDK** | `sdks/python/` | `openrag-sdk` on PyPI — a thin client for the OpenRAG REST API (chat, search, ingestion, settings). See `sdks/python/README.md` or run `/sdk`. |
| **TypeScript SDK** | `sdks/typescript/` | `openrag-sdk` on npm — same API surface as the Python SDK, for JS/TS apps. See `sdks/typescript/README.md`. |
| **MCP** | built into the backend, docs in `sdks/mcp/` | OpenRAG exposes a [Model Context Protocol](https://modelcontextprotocol.io/) server over streamable HTTP at `/mcp` (no separate process to run). Any MCP client (Cursor, Claude Desktop, etc.) can connect using an OpenRAG API key. The old standalone `openrag-mcp` PyPI package is deprecated — use the built-in endpoint instead. |
| **Flows** | `flows/` | Langflow flow JSON definitions (ingestion, retrieval, agents) that ship with OpenRAG. |
| **Docs** | `docs/` | The docs site source (published to [docs.openr.ag](https://docs.openr.ag)). |
| **Kubernetes operator** | `kubernetes/operator/` | Go operator for running OpenRAG on Kubernetes; see `kubernetes/operator/README.md`. |

If you're a first-time contributor, the [Development Workflows](#development-workflows) section below is the fastest way to get all of these running locally.

---

## Prerequisites

### Required Tools

| Tool | Version | Installation |
|------|---------|--------------|
| Docker, Podman, or Colima | Latest | [Docker](https://docs.docker.com/get-docker/), [Podman](https://podman.io/getting-started/installation), or [Colima](https://github.com/abiosoft/colima) |
| Python | 3.13+ | With [uv](https://github.com/astral-sh/uv) package manager |
| Node.js | 18+ | With npm |
| Make | Any | Usually pre-installed on macOS/Linux |

You only need one container runtime — pick whichever you're comfortable with. On macOS, most contributors use either Colima (lightweight, scriptable, no GUI) or Podman.

### Colima Setup (macOS)

[Colima](https://github.com/abiosoft/colima) runs a Linux VM and exposes a standard `docker` CLI/socket, so the Makefile's `docker compose` commands work without any changes — it's a drop-in replacement for Docker Desktop.

```bash
colima start \
  --cpu 8 \
  --memory 16 \
  --vm-type vz \
  --vz-rosetta \
  --mount-type virtiofs \
  --ssh-port 2222 \
  --port-forwarder grpc
```

What these flags are doing:

| Flag | Why |
|---|---|
| `--cpu 8 --memory 16` | Gives the VM enough headroom to run OpenSearch, Langflow, and Docling side by side. Lower is fine for a lighter stack (e.g. just `make backend` + `make frontend`), but 8 CPU / 16GB is comfortable for the full stack. |
| `--vm-type vz` | Uses Apple's native Virtualization.framework instead of QEMU — noticeably faster on Apple Silicon. |
| `--vz-rosetta` | Enables Rosetta translation inside the VM, so `x86_64` images run at near-native speed on Apple Silicon. |
| `--mount-type virtiofs` | Faster host↔VM filesystem mounts than the default (matters for volume-mounted dev reloads). |
| `--ssh-port 2222` | Avoids clashing with a real SSH server on port 22. |
| `--port-forwarder grpc` | More reliable port forwarding for the many ports OpenRAG exposes (3000, 7860, 8000, 9200, 5601, ...). |

Once Colima is running, `docker` (and `docker compose`) point at it automatically — everything in this guide works as-is. Useful commands:

```bash
colima status   # check the VM is running
colima stop     # stop the VM
colima delete   # remove the VM entirely (fresh start)
```

> [!TIP]
> If you resize the VM later, just `colima stop` and re-run `colima start` with the new flags.

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

2. Configure the required environment variables before starting OpenRAG. Start with `.env.example`; `make dev-local`, `make dev-local-cpu`, and the full-stack Make targets validate these values:

   ```env
   LANGFLOW_SUPERUSER=admin
   LANGFLOW_SUPERUSER_PASSWORD=
   LANGFLOW_SECRET_KEY=
   OPENSEARCH_PASSWORD=
   ```

   Configure a model provider, such as `OPENAI_API_KEY`, as required for the functionality you want to use.
   The `OPENSEARCH_PASSWORD` must adhere to the [OpenSearch password complexity requirements](https://docs.opensearch.org/latest/security/configuration/demo-configuration/#setting-up-a-custom-admin-password).

   You can reuse the credentials and generated secrets from a `.env` created by the OpenRAG terminal UI. Do not reuse its `~/.openrag` path settings for checkout development: leave the repository-relative defaults in place for `OPENRAG_DOCUMENTS_PATH(S)`, `OPENRAG_KEYS_PATH`, `OPENRAG_FLOWS_PATH`, `OPENRAG_CONFIG_PATH`, `OPENRAG_DATA_PATH`, and `LANGFLOW_DATA_PATH`.

   For more information, see the [OpenRAG environment variables reference](https://docs.openr.ag/reference/configuration).

3. Start OpenRAG using one of the workflows described in the next section. For normal code changes, use [Local Development](#local-development-recommended-for-development).

---

## Development Workflows

There are multiple ways to start OpenRAG based on your use case:

* Local development environment: Recommended for development.
* Full Docker stack: Run published images or build all images from the checkout. The latter is useful for testing the full system.
* Branch development: Build OpenRAG with a fork or branch of the [Langflow repository](https://github.com/langflow-ai/langflow).
* Docling only: Run the Docling service by itself.

### Keep terminal-managed versions and checked-out flows compatible

When you run `uv run openrag` from this repository, the OpenRAG terminal UI reads the version from `pyproject.toml` (via the installed package metadata) and writes that value to `OPENRAG_VERSION` before it starts services. Docker Compose then uses that value to pull the OpenRAG images from Docker Hub.

The flows used during development come from the checked-out source, not from those pulled images. Therefore, when starting services through `uv run openrag`, check out the release tag that matches the version in `pyproject.toml`. For example, a checkout containing version `0.5.0` must use the corresponding `0.5.0` release tag and images.

> [!WARNING]
> Do not run a newer or older branch's flows with a differently-versioned OpenRAG image. Flow components and their expected behavior can change between releases, so this mismatch can cause flows to fail or behave incorrectly.

### Full Docker Stack (Published Images)

Everything runs in containers using the image tag configured by `OPENRAG_VERSION` (or `OPENRAG_IMAGE_TAG`). This is convenient for running a released version, but it does not use local backend or frontend code.

```bash
make dev          # Start with GPU support
make dev-cpu      # Start with CPU only
make stop         # Stop and remove all containers
```

### Local Development (Recommended for Development)

> [!TIP]
> This is the **recommended workflow** for active development. It provides faster code reloading and easier debugging.

Run the infrastructure in Docker, but the backend and frontend from the current checkout. `make dev-local` and `make dev-local-cpu` rebuild the Langflow and OpenSearch images from the Dockerfiles in your branch, so the infrastructure stays aligned with the source you are developing.

```bash
# Terminal 1: Start infrastructure (OpenSearch, Langflow, Dashboards).
# Use make dev-local for GPU support.
make dev-local-cpu

# Terminal 2: Run backend locally
make backend

# Terminal 3: Run frontend locally
make frontend

# Terminal 4: Start Docling for document processing
make docling
```

The frontend automatically picks up changes. Restart `make backend` after backend changes.

> [!TIP]
> When running the backend with `make backend`, you can access the interactive API documentation at http://localhost:8000/docs.

### Run two local OpenRAG instances

Give the second instance its own environment file, then pass that file to every `make` command for that instance. Set a unique Compose project name and host ports so its containers and services do not conflict with the first instance:

```env
# .env.openrag-1
OPENRAG_BACKEND_PORT=8001
COMPOSE_PROJECT_NAME=openrag-1

FRONTEND_PORT=3001
LANGFLOW_PORT=7861
OPENSEARCH_PORT=9201
OPENSEARCH_DASHBOARDS_PORT=5602
OPENSEARCH_PERF_PORT=9601

# Target the second frontend when running frontend end-to-end tests.
BASE_URL=http://localhost:3001

# Keep the Langflow link in the OpenRAG UI correct.
LANGFLOW_PUBLIC_URL=http://localhost:7861
```

Start it with the same local-development commands, adding `ENV_FILE=.env.openrag-1` to each command:

```bash
make ENV_FILE=.env.openrag-1 dev-local-cpu
make ENV_FILE=.env.openrag-1 backend
make ENV_FILE=.env.openrag-1 frontend
```

Both instances can use the same host Docling process; start it once with `make docling`.

`BASE_URL` is used by the frontend end-to-end test tooling; it does not configure the running application. If both instances need independent persistent state, also give the second environment file unique values for `LANGFLOW_DATA_PATH`, `OPENRAG_DATA_PATH`, `OPENRAG_CONFIG_PATH`, `OPENRAG_KEYS_PATH`, `OPENRAG_DOCUMENTS_PATH`, and `OPENRAG_FLOWS_PATH`.

### Full Docker Stack (Build from This Checkout)

To build and run every OpenRAG container from the current checkout, use a build target. The backend and frontend run in containers, so only Docling needs to be started separately on the host.

```bash
# GPU support
make dev-build

# Or CPU only
make dev-build-cpu

# In another terminal: start Docling
make docling
```

### C) Branch Development (Custom Langflow)

If you need to test a Langflow change that hasn't shipped yet — your own fork/branch, or an upstream feature branch — use `dev-branch` instead of `dev`/`dev-cpu`. Instead of pulling the published Langflow image, it clones `REPO` at `BRANCH` and builds the Langflow image from source, then starts the rest of the stack normally:

```bash
# Full stack with custom branch
make dev-branch BRANCH=my-feature-branch

# Or CPU-only full stack
make dev-branch-cpu BRANCH=my-feature-branch

# Local development infrastructure (OpenSearch + custom Langflow container, backend/frontend on host)
make dev-branch-local BRANCH=my-feature-branch

# Or CPU-only local development infrastructure
make dev-branch-local-cpu BRANCH=my-feature-branch

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

## Frequently Used `make` Commands

A quick-reference cheat sheet of the commands you'll reach for most while contributing. Run `make help` at any time for the full, color-coded list.

| Command | What it does |
|---|---|
| `make check_tools` | Verify Docker/Podman/Colima, Python, uv, Node.js, and npm are installed and meet version requirements. |
| `make setup` | Install backend + frontend dependencies and scaffold `.env` from `.env.example`. Run once, and again after pulling changes that touch dependencies. |
| `make dev` / `make dev-cpu` | Start the **full stack** from the configured published images (GPU or CPU). |
| `make dev-build` / `make dev-build-cpu` | Build the complete stack from the current checkout, then run it in containers (GPU or CPU). Start Docling separately with `make docling`. |
| `make dev-local` / `make dev-local-cpu` | Build and start **infra only** (OpenSearch, Dashboards, Langflow) with the source in the current checkout; run backend/frontend on the host. This is the recommended active-development loop — see [Local Development](#local-development-recommended-for-development). |
| `make backend` | Run the FastAPI backend on the host (`uv run python src/main.py`). Restart it after backend changes. Requires infrastructure started via `make dev-local` or `make dev-local-cpu` first. |
| `make frontend` | Run the Next.js frontend on the host (`npx next dev`), with automatic reload on changes. |
| `make docling` / `make docling-stop` | Start/stop the host Docling service used for document parsing and OCR. |
| `make dev-branch BRANCH=<name>` | Build and run the full stack with a custom Langflow branch instead of the published image — see [Branch Development](#c-branch-development-custom-langflow). |
| `make stop` | Stop and remove all OpenRAG containers. |
| `make clean` | Stop containers and delete volumes (data is wiped). |
| `make factory-reset` | Full reset — containers, volumes, and on-disk data. Use when you want a completely clean slate. |
| `make logs` / `make logs-be` / `make logs-fe` / `make logs-lf` | Tail logs for all services, or just backend/frontend/Langflow. |
| `make status` / `make health` | Check container status / service health. |
| `make test` | Run the backend test suite. |
| `make lint` | Run linting checks. |
| `make help` | Show the full command reference, grouped by category (`make help_dev`, `make help_docker`, `make help_test`, `make help_local`, `make help_utils`). |

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
> This stops and removes containers and volumes, then deletes local Langflow data, backend configuration and data, and generated JWT keys. Use only when you need a completely fresh start.

```bash
make factory-reset  # Complete reset: containers, volumes, and data
```

After confirming the prompt, start the development workflow again with `make dev-local` or `make dev-local-cpu`, then run `make backend`, `make frontend`, and `make docling` in separate terminals.

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
# For Colima, stop and restart with more resources
colima stop
colima start --cpu 8 --memory 16 --vm-type vz --vz-rosetta --mount-type virtiofs --ssh-port 2222 --port-forwarder grpc

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
