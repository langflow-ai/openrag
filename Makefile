# Podman compose for OpenSearch + Langflow (dev dependencies)

COMPOSE_FILE ?= docker-compose-cpu.yml
PODMAN_COMPOSE ?= podman compose -f $(COMPOSE_FILE)
SERVICES ?= opensearch langflow
ENV_FILE ?= .env

.PHONY: check-env deps-up deps-stop deps-down deps-restart deps-logs deps-ps deps-pull deps-health

check-env:
	@test -f $(ENV_FILE) || (echo "Missing $(ENV_FILE). Create it with OPENSEARCH_PASSWORD and OPENAI_API_KEY."; exit 1)
	@test -n "$$(grep -E '^OPENSEARCH_PASSWORD=' $(ENV_FILE) | cut -d= -f2)" || (echo "OPENSEARCH_PASSWORD not set in $(ENV_FILE)"; exit 1)
	@test -n "$$(grep -E '^OPENAI_API_KEY=' $(ENV_FILE) | cut -d= -f2)" || (echo "OPENAI_API_KEY not set in $(ENV_FILE)"; exit 1)

podman-deps-up: check-env
	$(PODMAN_COMPOSE) pull $(SERVICES)
	$(PODMAN_COMPOSE) up -d --no-deps $(SERVICES)
	@echo "OpenSearch: https://localhost:9200"
	@echo "Langflow:   http://localhost:7860"

podman-deps-stop:
	$(PODMAN_COMPOSE) stop $(SERVICES)

podman-deps-down:
	$(PODMAN_COMPOSE) down

podman-deps-restart:
	$(PODMAN_COMPOSE) restart $(SERVICES)

podman-deps-logs:
	$(PODMAN_COMPOSE) logs -f $(SERVICES)

podman-deps-ps:
	$(PODMAN_COMPOSE) ps

podman-deps-pull:
	$(PODMAN_COMPOSE) pull $(SERVICES)

podman-deps-health:
	@echo "Checking OpenSearch (expect 200 or 401)..."
	@curl -k -u admin:$$OPENSEARCH_PASSWORD -sS -o /dev/null -w "%{http_code}\n" https://localhost:9200 || true
	@echo "Checking Langflow (expect 200)..."
	@curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:7860 || true

# OpenRAG Makefile
# Standard commands for running OpenRAG in production and development modes

.PHONY: help install install-frontend run backend frontend dev dev-all clean lint test build docker-build docker-up docker-down

# Default target
help:
	@echo "OpenRAG - Available commands:"
	@echo ""
	@echo "Installation:"
	@echo "  install           Install all dependencies (backend + frontend)"
	@echo "  install-frontend  Install frontend dependencies only"
	@echo ""
	@echo "Development:"
	@echo "  dev              Run both backend and frontend in development mode"
	@echo "  backend          Run backend server only"
	@echo "  frontend         Run frontend development server only"
	@echo ""
	@echo "Production:"
	@echo "  run              Run backend in production mode"
	@echo "  build            Build frontend for production"
	@echo ""
	@echo "Docker:"
	@echo "  docker-build     Build Docker images"
	@echo "  docker-up        Start services with docker-compose"
	@echo "  docker-up-cpu    Start services with docker-compose (CPU mode)"
	@echo "  docker-down      Stop docker-compose services"
	@echo "  docker-down-cpu  Stop docker-compose services (CPU mode)"
	@echo ""
	@echo "Utilities:"
	@echo "  lint             Run linting checks"
	@echo "  clean            Clean build artifacts and dependencies"
	@echo "  test             Run tests (if available)"
	@echo ""
	@echo "Quick check:"
	@echo "  check            Test backend health endpoint"

# Installation
install: install-frontend
	@echo "Installing backend dependencies..."
	uv sync

install-frontend:
	@echo "Installing frontend dependencies..."
	cd frontend && npm install

# Backend commands
backend:
	@echo "Starting backend server..."
	PYTHONPATH=src uv run python src/main.py

run: backend

# Frontend commands  
frontend:
	@echo "Starting frontend development server..."
	cd frontend && npm run dev

build:
	@echo "Building frontend for production..."
	cd frontend && npm run build

# Development mode
dev:
	@echo "Starting development mode..."
	@echo "This will start both backend and frontend servers."
	@echo "Backend: http://localhost:8000"
	@echo "Frontend: http://localhost:3000"
	@echo ""
	@echo "Starting backend in background..."
	@PYTHONPATH=src uv run python src/main.py &
	@sleep 3
	@echo "Starting frontend..."
	@cd frontend && npm run dev

# Alternative dev command that runs both services in parallel
dev-all:
	@echo "Starting both backend and frontend in parallel..."
	@echo "Use Ctrl+C to stop both services"
	@(PYTHONPATH=src uv run python src/main.py &) && (cd frontend && npm run dev)

# Utilities
lint:
	@echo "Running backend linting..."
	@if command -v ruff > /dev/null 2>&1; then \
		ruff check .; \
	else \
		echo "Ruff not found, skipping backend linting"; \
	fi
	@echo "Running frontend linting..."
	@cd frontend && npm run lint

test:
	@echo "Running tests..."
	@if [ -f "pytest.ini" ] || [ -f "pyproject.toml" ]; then \
		uv run pytest; \
	else \
		echo "No test configuration found"; \
	fi

check:
	@echo "Checking backend health..."
	@curl -s http://localhost:8000/.well-known/openid-configuration > /dev/null && echo "✓ Backend is running" || echo "✗ Backend not responding"

clean:
	@echo "Cleaning build artifacts..."
	rm -rf frontend/.next
	rm -rf frontend/node_modules
	rm -rf .venv
	rm -rf src/__pycache__
	rm -rf **/__pycache__

# Docker commands
docker-build:
	@echo "Building Docker images..."
	docker-compose build

docker-up:
	@echo "Starting services with docker-compose..."
	docker-compose up -d

docker-up-cpu:
	@echo "Starting services with docker-compose (CPU mode)..."
	docker-compose -f docker-compose-cpu.yml up -d

docker-down:
	@echo "Stopping docker-compose services..."
	docker-compose down

docker-down-cpu:
	@echo "Stopping docker-compose services (CPU mode)..."
	docker-compose -f docker-compose-cpu.yml down