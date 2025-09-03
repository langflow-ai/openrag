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