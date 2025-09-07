# OpenRAG Development Guide

A comprehensive guide for setting up and developing OpenRAG locally.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Environment Setup](#environment-setup)
- [Development Methods](#development-methods)
- [Local Development (Non-Docker)](#local-development-non-docker)
- [Docker Development](#docker-development)
- [API Documentation](#api-documentation)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

## Architecture Overview

OpenRAG consists of four main services:

1. **Backend** (`src/`) - Python FastAPI/Starlette application with document processing, search, and chat
2. **Frontend** (`frontend/`) - Next.js React application
3. **OpenSearch** - Document storage and vector search engine
4. **Langflow** - AI workflow engine for chat functionality

### Key Technologies

- **Backend**: Python 3.13+, Starlette, OpenAI, Docling, OpenSearch
- **Frontend**: Next.js 15, React 19, TypeScript, Tailwind CSS
- **Dependencies**: UV (Python), npm (Node.js)
- **Containerization**: Docker/Podman with Compose

## Prerequisites

### System Requirements

- **Python**: 3.13+ (for local development)
- **Node.js**: 18+ (for frontend development)
- **Container Runtime**: Docker or Podman with Compose
- **Memory**: 8GB+ RAM recommended (especially for GPU workloads)

### Development Tools

```bash
# Python dependency manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Node.js (via nvm recommended)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
nvm install 18
nvm use 18
```

## Environment Setup

### 1. Clone and Setup

```bash
git clone <repository-url>
cd openrag
```

### 2. Environment Variables

Create your environment configuration:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```bash
# Required
OPENSEARCH_PASSWORD=your_secure_password
OPENAI_API_KEY=sk-your_openai_api_key

# Langflow Configuration
LANGFLOW_PUBLIC_URL=http://localhost:7860
LANGFLOW_SUPERUSER=admin
LANGFLOW_SUPERUSER_PASSWORD=your_langflow_password
LANGFLOW_SECRET_KEY=your_secret_key_min_32_chars
LANGFLOW_AUTO_LOGIN=true
LANGFLOW_NEW_USER_IS_ACTIVE=true
LANGFLOW_ENABLE_SUPERUSER_CLI=true
FLOW_ID=your_flow_id

# OAuth (Optional - for Google Drive/OneDrive connectors)
GOOGLE_OAUTH_CLIENT_ID=your_google_client_id
GOOGLE_OAUTH_CLIENT_SECRET=your_google_client_secret
MICROSOFT_GRAPH_OAUTH_CLIENT_ID=your_microsoft_client_id
MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET=your_microsoft_client_secret

# Webhooks (Optional)
WEBHOOK_BASE_URL=https://your-domain.com

# AWS S3 (Optional)
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
```

## Development Methods

Choose your preferred development approach:

## Local Development (Non-Docker)

Best for rapid development and debugging.

### Backend Setup

```bash
# Install Python dependencies
uv sync

# Start OpenSearch (required dependency)
docker run -d \
  --name opensearch-dev \
  -p 9200:9200 \
  -p 9600:9600 \
  -e "discovery.type=single-node" \
  -e "OPENSEARCH_INITIAL_ADMIN_PASSWORD=admin123" \
  opensearchproject/opensearch:3.0.0

# Start backend
cd src
uv run python main.py
```

Backend will be available at: http://localhost:8000

### Frontend Setup

```bash
# Install Node.js dependencies
cd frontend
npm install

# Start development server
npm run dev
```

Frontend will be available at: http://localhost:3000

### Langflow Setup (Optional)

```bash
# Install and run Langflow
pip install langflow
langflow run --host 0.0.0.0 --port 7860
```

Langflow will be available at: http://localhost:7860

## Docker Development

Use this for a production-like environment or when you need all services.

### Available Compose Files

- `docker-compose-dev.yml` - Development (builds from source)
- `docker-compose.yml` - Production (pre-built images)
- `docker-compose-cpu.yml` - CPU-only version

### Development with Docker

```bash
# Build and start all services
docker compose -f docker-compose-dev.yml up --build

# Or with Podman
podman compose -f docker-compose-dev.yml up --build

# Run in background
docker compose -f docker-compose-dev.yml up --build -d

# View logs
docker compose -f docker-compose-dev.yml logs -f

# Stop services
docker compose -f docker-compose-dev.yml down
```

### Service Ports

- **Frontend**: http://localhost:3000
- **Backend**: http://localhost:8000 (internal)
- **OpenSearch**: http://localhost:9200
- **OpenSearch Dashboards**: http://localhost:5601
- **Langflow**: http://localhost:7860

### Reset Development Environment

```bash
# Complete reset (removes volumes and rebuilds)
docker compose -f docker-compose-dev.yml down -v
docker compose -f docker-compose-dev.yml up --build --force-recreate --remove-orphans
```

## API Documentation

### Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/search` | POST | Search documents with filters |
| `/upload` | POST | Upload documents |
| `/upload_path` | POST | Upload from local path |
| `/tasks` | GET | List processing tasks |
| `/tasks/{id}` | GET | Get task status |
| `/connectors` | GET | List available connectors |
| `/auth/me` | GET | Get current user info |
| `/knowledge-filter` | POST/GET | Manage knowledge filters |

### Example API Calls

```bash
# Search all documents
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "*", "limit": 100}'

# Upload a document
curl -X POST http://localhost:8000/upload \
  -F "file=@document.pdf"

# Get task status
curl http://localhost:8000/tasks/task_id_here
```

### Frontend API Proxy

The Next.js frontend proxies API calls through `/api/*` to the backend at `http://openrag-backend:8000` (in Docker) or `http://localhost:8000` (local).

## Troubleshooting

### Common Issues

#### Docker/Podman Issues

**Issue**: `docker: command not found`
```bash
# Install Docker Desktop or use Podman
brew install podman podman-desktop
podman machine init --memory 8192
podman machine start
```

**Issue**: Out of memory during build
```bash
# For Podman on macOS
podman machine stop
podman machine rm
podman machine init --memory 8192
podman machine start
```

#### Backend Issues

**Issue**: `ModuleNotFoundError` or dependency issues
```bash
# Ensure you're using the right Python version
python --version  # Should be 3.13+
uv sync --reinstall
```

**Issue**: OpenSearch connection failed
```bash
# Check if OpenSearch is running
curl -k -u admin:admin123 https://localhost:9200
# If using Docker, ensure the container is running
docker ps | grep opensearch
```

**Issue**: CUDA/GPU not detected
```bash
# Check GPU availability
python -c "import torch; print(torch.cuda.is_available())"
# For CPU-only development, use docker-compose-cpu.yml
```

#### Frontend Issues

**Issue**: Next.js build failures
```bash
# Clear cache and reinstall
cd frontend
rm -rf .next node_modules package-lock.json
npm install
npm run dev
```

**Issue**: API calls failing
- Check that backend is running on port 8000
- Verify environment variables are set correctly
- Check browser network tab for CORS or proxy issues

#### Document Processing Issues

**Issue**: Docling model download failures
```bash
# Pre-download models
uv run docling-tools models download
# Or clear cache and retry
rm -rf ~/.cache/docling
```

**Issue**: EasyOCR initialization errors
```bash
# Clear EasyOCR cache
rm -rf ~/.EasyOCR
# Restart the backend to reinitialize
```

### Development Tips

1. **Hot Reloading**: 
   - Backend: Use `uvicorn src.main:app --reload` for auto-restart
   - Frontend: `npm run dev` provides hot reloading

2. **Debugging**:
   - Add `print()` statements or use `pdb.set_trace()` in Python
   - Use browser dev tools for frontend debugging
   - Check Docker logs: `docker compose logs -f service_name`

3. **Database Inspection**:
   - Access OpenSearch Dashboards at http://localhost:5601
   - Use curl to query OpenSearch directly
   - Check the `documents` index for uploaded content

4. **Performance**:
   - GPU processing is much faster for document processing
   - Use CPU-only mode if GPU issues occur
   - Monitor memory usage with `docker stats` or `htop`

### Log Locations

- **Backend**: Console output or container logs
- **Frontend**: Browser console and Next.js terminal
- **OpenSearch**: Container logs (`docker compose logs opensearch`)
- **Langflow**: Container logs (`docker compose logs langflow`)

## Contributing

### Code Style

- **Python**: Follow PEP 8, use `black` for formatting
- **TypeScript**: Use ESLint configuration in `frontend/`
- **Commits**: Use conventional commit messages

### Development Workflow

1. Create feature branch from `main`
2. Make changes and test locally
3. Run tests (if available)
4. Create pull request with description
5. Ensure all checks pass

### Testing

```bash
# Backend tests (if available)
cd src
uv run pytest

# Frontend tests (if available)
cd frontend
npm test

# Integration tests with Docker
docker compose -f docker-compose-dev.yml up --build
# Test API endpoints manually or with automated tests
```

## Additional Resources

- [OpenSearch Documentation](https://opensearch.org/docs/)
- [Langflow Documentation](https://docs.langflow.org/)
- [Next.js Documentation](https://nextjs.org/docs)
- [Starlette Documentation](https://www.starlette.io/)
- [Docling Documentation](https://ds4sd.github.io/docling/)

---

For questions or issues, please check the troubleshooting section above or create an issue in the repository.
