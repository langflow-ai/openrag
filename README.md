# OpenRAG

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/phact/openrag)

OpenRAG is a comprehensive Retrieval-Augmented Generation platform that enables intelligent document search and AI-powered conversations. Users can upload, process, and query documents through a chat interface backed by large language models and semantic search capabilities. The system utilizes Langflow for document ingestion, retrieval workflows, and intelligent nudges, providing a seamless RAG experience. Built with Starlette, Next.js, OpenSearch, and Langflow integration.

## 📋 Table of Contents

- [Quick Start](#quick-start)
- [Development](#development)
- [Configuration](#configuration)
- [Docker Deployment](#docker-deployment)
- [Troubleshooting](#troubleshooting)

## 🚀 Quick Start

### Prerequisites

- Docker or Podman with Compose installed
- Make (for development commands)

### 1. Environment Setup

```bash
# Clone and setup environment
git clone <repository-url>
cd openrag
make setup  # Creates .env and installs dependencies
```

### 2. Configure Environment

Edit `.env` with your API keys and credentials:

```bash
# Required
OPENAI_API_KEY=your_openai_api_key
OPENSEARCH_PASSWORD=your_secure_password
LANGFLOW_SUPERUSER=admin
LANGFLOW_SUPERUSER_PASSWORD=your_secure_password
LANGFLOW_CHAT_FLOW_ID=your_chat_flow_id
LANGFLOW_INGEST_FLOW_ID=your_ingest_flow_id
NUDGES_FLOW_ID=your_nudges_flow_id
```

### 3. Start OpenRAG

```bash
# Full stack with GPU support
make dev

# Or CPU only
make dev-cpu
```

Access the services:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **Langflow**: http://localhost:7860
- **OpenSearch**: http://localhost:9200
- **OpenSearch Dashboards**: http://localhost:5601

## 🛠️ Development

### Development Commands

All development tasks are managed through the Makefile. Run `make help` to see all available commands.

#### Environment Management

```bash
# Setup development environment
make setup                    # Initial setup: creates .env, installs dependencies

# Start development environments
make dev                     # Full stack with GPU support
make dev-cpu                 # Full stack with CPU only
make dev-local               # Infrastructure only (for local development)
make infra                   # Alias for dev-local

# Container management
make stop                    # Stop all containers
make restart                 # Restart all containers
make clean                   # Stop and remove containers/volumes
make status                  # Show container status
make health                  # Check service health
```

#### Local Development

For faster development iteration, run infrastructure in Docker and backend/frontend locally:

```bash
# Terminal 1: Start infrastructure
make dev-local

# Terminal 2: Run backend locally
make backend

# Terminal 3: Run frontend locally  
make frontend
```

#### Dependency Management

```bash
make install                 # Install all dependencies
make install-be             # Install backend dependencies (uv)
make install-fe             # Install frontend dependencies (npm)
```

#### Building and Testing

```bash
# Build Docker images
make build                   # Build all images
make build-be               # Build backend image only
make build-fe               # Build frontend image only

# Testing and quality
make test                   # Run backend tests
make lint                   # Run linting checks
```

#### Debugging

```bash
# View logs
make logs                   # All container logs
make logs-be                # Backend logs only
make logs-fe                # Frontend logs only
make logs-lf                # Langflow logs only
make logs-os                # OpenSearch logs only


#### Database Operations

```bash
# Reset OpenSearch indices
make db-reset               # Delete and recreate indices
```


## ⚙️ Configuration

### Environment Variables

OpenRAG uses environment variables for configuration. All variables should be set in your `.env` file.

#### Required Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Your OpenAI API key |
| `OPENSEARCH_PASSWORD` | Password for OpenSearch admin user |
| `LANGFLOW_SUPERUSER` | Langflow admin username |
| `LANGFLOW_SUPERUSER_PASSWORD` | Langflow admin password |
| `LANGFLOW_CHAT_FLOW_ID` | ID of your Langflow chat flow |
| `LANGFLOW_INGEST_FLOW_ID` | ID of your Langflow ingestion flow |
| `NUDGES_FLOW_ID` | ID of your Langflow nudges/suggestions flow |

#### Ingestion Configuration

| Variable | Description |
|----------|-------------|
| `DISABLE_INGEST_WITH_LANGFLOW` | Disable Langflow ingestion pipeline (default: `false`) |

- `false` or unset: Uses Langflow pipeline (upload → ingest → delete)
- `true`: Uses traditional OpenRAG processor for document ingestion

#### Optional Variables

| Variable | Description |
|----------|-------------|
| `LANGFLOW_PUBLIC_URL` | Public URL for Langflow (default: `http://localhost:7860`) |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth authentication |
| `MICROSOFT_GRAPH_OAUTH_CLIENT_ID` / `MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET` | Microsoft OAuth |
| `WEBHOOK_BASE_URL` | Base URL for webhook endpoints |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | AWS integrations |
| `SESSION_SECRET` | Session management (default: auto-generated, change in production) |
| `LANGFLOW_KEY` | Explicit Langflow API key (auto-generated if not provided) |
| `LANGFLOW_SECRET_KEY` | Secret key for Langflow internal operations |

## 🐳 Docker Deployment

### Standard Deployment

```bash
# Build and start all services
docker compose build
docker compose up -d
```

### CPU-Only Deployment

For environments without GPU support:

```bash
docker compose -f docker-compose-cpu.yml up -d
```

### Force Rebuild

If you need to reset state or rebuild everything:

```bash
docker compose up --build --force-recreate --remove-orphans
```

### Service URLs

After deployment, services are available at:

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **Langflow**: http://localhost:7860
- **OpenSearch**: http://localhost:9200
- **OpenSearch Dashboards**: http://localhost:5601

## 🔧 Troubleshooting

### Podman on macOS

If using Podman on macOS, you may need to increase VM memory:

```bash
podman machine stop
podman machine rm
podman machine init --memory 8192   # 8 GB example
podman machine start
```

### Common Issues

1. **OpenSearch fails to start**: Check that `OPENSEARCH_PASSWORD` is set and meets requirements
2. **Langflow connection issues**: Verify `LANGFLOW_SUPERUSER` credentials are correct
3. **Out of memory errors**: Increase Docker memory allocation or use CPU-only mode
4. **Port conflicts**: Ensure ports 3000, 7860, 8000, 9200, 5601 are available



### Development Tips

- Use `make infra` + `make backend` + `make frontend` for faster development iteration
- Run `make help` to see all available commands
- Check `.env.example` for complete environment variable documentation