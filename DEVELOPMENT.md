# OpenRAG Development Guide

Quick start commands using the Makefile for development and production workflows.

## 🚀 Quick Start

### First Time Setup
```bash
# Install all dependencies (backend + frontend)
make install

# Or install individually
make install-frontend  # Frontend only
uv sync                 # Backend only
```

### Development Mode
```bash
# Start both backend and frontend (recommended)
make dev

# Or run services individually
make backend    # Backend only (http://localhost:8000)
make frontend   # Frontend only (http://localhost:3000)

# Alternative: Run both in parallel
make dev-all
```

## 🛠️ Available Commands

### Development
| Command | Description |
|---------|-------------|
| `make dev` | Start both backend and frontend servers |
| `make dev-all` | Start both services in parallel |
| `make backend` | Run backend server only |
| `make frontend` | Run frontend development server only |

### Production
| Command | Description |
|---------|-------------|
| `make run` | Run backend in production mode |
| `make build` | Build frontend for production |

### Installation
| Command | Description |
|---------|-------------|
| `make install` | Install all dependencies |
| `make install-frontend` | Install frontend dependencies only |

### Docker
| Command | Description |
|---------|-------------|
| `make docker-build` | Build Docker images |
| `make docker-up` | Start services with docker-compose |
| `make docker-up-cpu` | Start services (CPU mode) |
| `make docker-down` | Stop docker-compose services |
| `make docker-down-cpu` | Stop services (CPU mode) |

### Utilities
| Command | Description |
|---------|-------------|
| `make help` | Show all available commands |
| `make check` | Test backend health endpoint |
| `make lint` | Run linting checks |
| `make test` | Run tests |
| `make clean` | Clean build artifacts |

## 🌐 Service URLs

- **Backend API**: http://localhost:8000
- **Frontend**: http://localhost:3000
- **Health Check**: http://localhost:8000/.well-known/openid-configuration

## 📋 Environment Setup

### Backend Environment Variables
Create a `.env` file in the project root with:

```env
OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200
OPENSEARCH_USERNAME=admin
OPENSEARCH_PASSWORD=your_password
LANGFLOW_URL=http://localhost:7860
OPENAI_API_KEY=your_openai_key
```

### Manual Backend Run (Alternative)
```bash
# With inline environment variables
OPENSEARCH_HOST=localhost OPENSEARCH_PORT=9200 OPENSEARCH_USERNAME=admin OPENSEARCH_PASSWORD=... \
LANGFLOW_URL=http://localhost:7860 OPENAI_API_KEY=... \
uv run python src/main.py

# Using .env file (recommended)
uv run python src/main.py
```

## 🔧 Development Workflow

1. **Start Development**:
   ```bash
   make dev
   ```

2. **Check Services**:
   ```bash
   make check
   ```

3. **Run Tests & Linting**:
   ```bash
   make lint
   make test
   ```

4. **Build for Production**:
   ```bash
   make build
   ```

## 🐳 Docker Development

For containerized development:

```bash
# GPU mode (default)
make docker-up

# CPU mode
make docker-up-cpu

# Stop services
make docker-down        # GPU mode
make docker-down-cpu    # CPU mode
```

## 🆘 Troubleshooting

### Common Issues

**Backend not starting?**
- Check your `.env` file exists and has required variables
- Verify dependencies: `uv sync`
- Test manually: `uv run python src/main.py`

**Frontend not starting?**
- Install dependencies: `make install-frontend`
- Check Node.js version compatibility

**Import errors?**
- The Makefile sets `PYTHONPATH=src` automatically
- For manual runs: `PYTHONPATH=src uv run python src/main.py`

**Health check failing?**
```bash
make check
# or
curl http://localhost:8000/.well-known/openid-configuration
```

## 📚 Additional Resources

- Backend code: `src/`
- Frontend code: `frontend/`
- Docker configs: `docker-compose.yml`, `docker-compose-cpu.yml`
- Environment example: `.env.example`