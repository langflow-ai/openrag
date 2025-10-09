# Contributing to OpenRAG

Thank you for your interest in contributing to OpenRAG! This guide will help you set up your development environment and understand the development workflow.

## 🛠️ Development Setup

### Prerequisites

- Docker or Podman with Compose installed
- Make (for development commands)
- Python 3.13+ with uv package manager
- Node.js 18+ and npm

### Set up OpenRAG for development

1. Set up your development environment.

```bash
# Clone and setup environment
git clone https://github.com/langflow-ai/openrag.git
cd openrag
make setup  # Creates .env and installs dependencies
```

2. Configure the `.env` file with your API keys and credentials.

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

For extended configuration, including ingestion and optional variables, see [docs/reference/configuration.mdx](docs/docs/reference/configuration.mdx).

3. Start OpenRAG.

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

## 🔧 Development Commands

All development tasks are managed through the Makefile. Run `make help` to see all available commands.

### Environment Management

```bash
# Setup development environment
make setup                    # Initial setup: creates .env, installs dependencies

# Start development environments
make dev                     # Full stack with GPU support
make dev-cpu                 # Full stack with CPU only
make infra                   # Infrastructure only (for local development)

# Container management
make stop                    # Stop all containers
make restart                 # Restart all containers
make clean                   # Stop and remove containers/volumes
make status                  # Show container status
make health                  # Check service health
```

### Local Development Workflow

For faster development iteration, run infrastructure in Docker and backend/frontend locally:

```bash
# Terminal 1: Start infrastructure
make infra

# Terminal 2: Run backend locally
make backend

# Terminal 3: Run frontend locally  
make frontend
```

This setup provides:
- Faster code reloading
- Direct access to logs and debugging
- Easier testing and iteration

### Dependency Management

```bash
make install                 # Install all dependencies
make install-be             # Install backend dependencies (uv)
make install-fe             # Install frontend dependencies (npm)
```

### Building and Testing

```bash
# Build Docker images
make build                   # Build all images
make build-be               # Build backend image only
make build-fe               # Build frontend image only

# Testing and quality
make test                   # Run backend tests
make lint                   # Run linting checks
```

### Debugging

```bash
# View logs
make logs                   # All container logs
make logs-be                # Backend logs only
make logs-fe                # Frontend logs only
make logs-lf                # Langflow logs only
make logs-os                # OpenSearch logs only

# Shell access
make shell-be               # Shell into backend container
make shell-lf               # Shell into langflow container
make shell-os               # Shell into opensearch container
```

### Database Operations

```bash
# Reset OpenSearch indices
make db-reset               # Delete and recreate indices
```

### Flow Management

```bash
# Upload flow to Langflow
make flow-upload FLOW_FILE=path/to/flow.json
```

## 🏗️ Architecture Overview

### Backend (Python/Starlette)
- **API Layer**: RESTful endpoints in `src/api/`
- **Services**: Business logic in `src/services/`
- **Models**: Data models and processors in `src/models/`
- **Connectors**: External service integrations in `src/connectors/`
- **Configuration**: Settings management in `src/config/`

### Frontend (Next.js/React)
- **Pages**: Next.js app router in `frontend/src/app/`
- **Components**: Reusable UI components in `frontend/src/components/`
- **Contexts**: State management in `frontend/src/contexts/`
- **Hooks**: Custom React hooks in `frontend/hooks/`

### Infrastructure
- **OpenSearch**: Vector database and search engine
- **Langflow**: Visual flow builder for LLM workflows
- **Docker**: Containerization and orchestration

## 🧪 Testing

### Backend Tests
```bash
make test                   # Run all backend tests
uv run pytest              # Direct pytest execution
uv run pytest -v           # Verbose test output
```

### Frontend Tests
```bash
cd frontend && npm test     # Run frontend tests
cd frontend && npm run lint # Frontend linting
```

## 📝 Code Style

### Backend
- Follow PEP 8 style guidelines
- Use type hints where appropriate
- Document functions and classes with docstrings
- Use structured logging with `structlog`

### Frontend
- Follow React/Next.js best practices
- Use TypeScript for type safety
- Follow the established component structure
- Use Tailwind CSS for styling

## 🔍 Debugging Tips

### Backend Debugging
```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Run backend locally for debugging
make infra && make backend

# Check OpenSearch indices
curl -X GET "http://localhost:9200/_cat/indices?v" \
  -u admin:$(grep OPENSEARCH_PASSWORD .env | cut -d= -f2)
```

### Frontend Debugging
```bash
# Run with detailed logs
cd frontend && npm run dev

# Build and analyze bundle
cd frontend && npm run build
```

### Container Debugging
```bash
# Check container status
make status

# View real-time logs
make logs

# Shell into containers
make shell-be  # Backend container
make shell-lf  # Langflow container
```

## 🚀 Deployment Testing

### Local Testing
```bash
# Test full stack deployment
make clean && make dev

# Test CPU-only deployment
make clean && make dev-cpu
```

### Performance Testing
```bash
# Monitor resource usage
docker stats

# Check service health
make health
```

## 📚 Development Resources

### Key Files
- `src/main.py` - Backend application entry point
- `src/config/settings.py` - Configuration management
- `frontend/src/app/layout.tsx` - Frontend root layout
- `docker-compose.yml` - Container orchestration
- `Makefile` - Development commands

### Documentation
- API documentation: Available at `http://localhost:8000/docs` when backend is running
- Component Storybook: (if implemented) at `http://localhost:6006`
- OpenSearch: `http://localhost:5601` (Dashboards)
- Langflow: `http://localhost:7860`

## 🐛 Common Issues

### Port Conflicts
Ensure these ports are available:
- 3000 (Frontend)
- 7860 (Langflow)
- 8000 (Backend)
- 9200 (OpenSearch)
- 5601 (OpenSearch Dashboards)

### Memory Issues
- Use `make dev-cpu` for CPU-only mode
- Increase Docker memory allocation
- Podman on macOS: increase the VM memory if needed

```bash
podman machine stop
podman machine rm
podman machine init --memory 8192   # 8 GB example
podman machine start
```

### Environment Issues
```bash
# Reset environment
make clean
cp .env.example .env  # Reconfigure as needed
make setup
```

## 📋 Pull Request Guidelines

1. **Fork and Branch**: Create a feature branch from `main`
2. **Test**: Ensure all tests pass with `make test` and `make lint`
3. **Documentation**: Update relevant documentation
4. **Commit Messages**: Use clear, descriptive commit messages
5. **PR Description**: Explain changes and include testing instructions

## 🤝 Getting Help

- Check existing issues and discussions
- Use `make status` and `make health` for debugging
- Review logs with `make logs`
- Join our community discussions

Thank you for contributing to OpenRAG! 🚀
