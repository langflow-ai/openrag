# OpenRAG Development Makefile
# Provides easy commands for development workflow

.PHONY: help dev dev-cpu dev-local infra stop clean build logs shell-backend shell-frontend install test backend frontend install-be install-fe build-be build-fe logs-be logs-fe logs-lf logs-os shell-be shell-lf shell-os restart status health db-reset flow-upload quick setup setup-with-ui

# Default target
help:
	@echo "OpenRAG Development Commands"
	@echo ""
	@echo "Development:"
	@echo "  dev          - Start full stack with GPU support (docker compose)"
	@echo "  dev-cpu      - Start full stack with CPU only (docker compose)"
	@echo "  dev-local    - Start infrastructure only, run backend/frontend locally"
	@echo "  infra        - Start infrastructure services only (alias for dev-local)"
	@echo "  stop         - Stop all containers"
	@echo "  restart      - Restart all containers"
	@echo ""
	@echo "Local Development:"
	@echo "  backend      - Run backend locally (requires infrastructure)"
	@echo "  frontend     - Run frontend locally"
	@echo "  install      - Install all dependencies"
	@echo "  install-be   - Install backend dependencies (uv)"
	@echo "  install-fe   - Install frontend dependencies (npm)"
	@echo ""
	@echo "Setup:"
	@echo "  setup        - Install dependencies and create .env from template"
	@echo "  setup-with-ui - Full setup with configuration UI (recommended)"
	@echo ""
	@echo "Utilities:"
	@echo "  build        - Build all Docker images"
	@echo "  clean        - Stop containers and remove volumes"
	@echo "  logs         - Show logs from all containers"
	@echo "  logs-be      - Show backend container logs"
	@echo "  logs-lf      - Show langflow container logs"
	@echo "  shell-be     - Shell into backend container"
	@echo "  shell-lf     - Shell into langflow container"
	@echo ""
	@echo "Testing:"
	@echo "  test         - Run backend tests"
	@echo "  lint         - Run linting checks"
	@echo ""

# Development environments
dev:
	@echo "🚀 Starting OpenRAG with GPU support..."
	docker-compose up -d
	@echo "✅ Services started!"
	@echo "   Backend: http://localhost:8000"
	@echo "   Frontend: http://localhost:3000"
	@echo "   Langflow: http://localhost:7860"
	@echo "   OpenSearch: http://localhost:9200"
	@echo "   Dashboards: http://localhost:5601"

dev-cpu:
	@echo "🚀 Starting OpenRAG with CPU only..."
	docker-compose -f docker-compose-cpu.yml up -d
	@echo "✅ Services started!"
	@echo "   Backend: http://localhost:8000"
	@echo "   Frontend: http://localhost:3000"
	@echo "   Langflow: http://localhost:7860"
	@echo "   OpenSearch: http://localhost:9200"
	@echo "   Dashboards: http://localhost:5601"

dev-local:
	@echo "🔧 Starting infrastructure only (for local development)..."
	docker-compose up -d opensearch dashboards langflow
	@echo "✅ Infrastructure started!"
	@echo "   Langflow: http://localhost:7860"
	@echo "   OpenSearch: http://localhost:9200"
	@echo "   Dashboards: http://localhost:5601"
	@echo ""
	@echo "Now run 'make backend' and 'make frontend' in separate terminals"

infra:
	@echo "🔧 Starting infrastructure services only..."
	docker-compose up -d opensearch dashboards langflow
	@echo "✅ Infrastructure services started!"
	@echo "   Langflow: http://localhost:7860"
	@echo "   OpenSearch: http://localhost:9200"
	@echo "   Dashboards: http://localhost:5601"

# Container management
stop:
	@echo "🛑 Stopping all containers..."
	docker-compose down
	docker-compose -f docker-compose-cpu.yml down 2>/dev/null || true

restart: stop dev

clean: stop
	@echo "🧹 Cleaning up containers and volumes..."
	docker-compose down -v --remove-orphans
	docker-compose -f docker-compose-cpu.yml down -v --remove-orphans 2>/dev/null || true
	docker system prune -f

# Local development
backend:
	@echo "🐍 Starting backend locally..."
	@if [ ! -f .env ]; then echo "⚠️  .env file not found. Copy .env.example to .env first"; exit 1; fi
	uv run python src/main.py

frontend:
	@echo "⚛️  Starting frontend locally..."
	@if [ ! -d "frontend/node_modules" ]; then echo "📦 Installing frontend dependencies first..."; cd frontend && npm install; fi
	cd frontend && npx next dev

# Installation
install: install-be install-fe
	@echo "✅ All dependencies installed!"

install-be:
	@echo "📦 Installing backend dependencies..."
	uv sync

install-fe:
	@echo "📦 Installing frontend dependencies..."
	cd frontend && npm install

# Building
build:
	@echo "🔨 Building Docker images..."
	docker-compose build

build-be:
	@echo "🔨 Building backend image..."
	docker build -t openrag-backend -f Dockerfile.backend .

build-fe:
	@echo "🔨 Building frontend image..."
	docker build -t openrag-frontend -f Dockerfile.frontend .

# Logging and debugging
logs:
	@echo "📋 Showing all container logs..."
	docker-compose logs -f

logs-be:
	@echo "📋 Showing backend logs..."
	docker-compose logs -f openrag-backend

logs-fe:
	@echo "📋 Showing frontend logs..."
	docker-compose logs -f openrag-frontend

logs-lf:
	@echo "📋 Showing langflow logs..."
	docker-compose logs -f langflow

logs-os:
	@echo "📋 Showing opensearch logs..."
	docker-compose logs -f opensearch

# Shell access
shell-be:
	@echo "🐚 Opening shell in backend container..."
	docker-compose exec openrag-backend /bin/bash

shell-lf:
	@echo "🐚 Opening shell in langflow container..."
	docker-compose exec langflow /bin/bash

shell-os:
	@echo "🐚 Opening shell in opensearch container..."
	docker-compose exec opensearch /bin/bash

# Testing and quality
test:
	@echo "🧪 Running backend tests..."
	uv run pytest

lint:
	@echo "🔍 Running linting checks..."
	cd frontend && npm run lint
	@echo "Frontend linting complete"

# Service status
status:
	@echo "📊 Container status:"
	@docker-compose ps 2>/dev/null || echo "No containers running"

health:
	@echo "🏥 Health check:"
	@echo "Backend: $$(curl -s http://localhost:8000/health 2>/dev/null || echo 'Not responding')"
	@echo "Langflow: $$(curl -s http://localhost:7860/health 2>/dev/null || echo 'Not responding')"
	@echo "OpenSearch: $$(curl -s -k -u admin:$(shell grep OPENSEARCH_PASSWORD .env | cut -d= -f2) https://localhost:9200 2>/dev/null | jq -r .tagline 2>/dev/null || echo 'Not responding')"

# Database operations
db-reset:
	@echo "🗄️ Resetting OpenSearch indices..."
	curl -X DELETE "http://localhost:9200/documents" -u admin:$$(grep OPENSEARCH_PASSWORD .env | cut -d= -f2) || true
	curl -X DELETE "http://localhost:9200/knowledge_filters" -u admin:$$(grep OPENSEARCH_PASSWORD .env | cut -d= -f2) || true
	@echo "Indices reset. Restart backend to recreate."

# Flow management
flow-upload:
	@echo "📁 Uploading flow to Langflow..."
	@if [ -z "$(FLOW_FILE)" ]; then echo "Usage: make flow-upload FLOW_FILE=path/to/flow.json"; exit 1; fi
	curl -X POST "http://localhost:7860/api/v1/flows" \
		-H "Content-Type: application/json" \
		-d @$(FLOW_FILE)

# Quick development shortcuts
quick: dev-local
	@echo "🚀 Quick start: infrastructure running!"
	@echo "Run these in separate terminals:"
	@echo "  make backend"
	@echo "  make frontend"

# Environment setup
setup:
	@echo "⚙️ Setting up development environment..."
	@if [ ! -f .env ]; then cp .env.example .env && echo "📝 Created .env from template"; fi
	@$(MAKE) install
	@echo "✅ Setup complete! Run 'make dev' to start."

setup-with-ui:
	@echo "🚀 Starting OpenRAG setup with configuration UI..."
	@echo "📝 Starting init-ui container for configuration..."
	docker-compose -f docker-compose-cpu.yml --profile setup up -d --force-recreate --build
	@echo "🌐 Configuration UI started at http://localhost:8080"
	@echo "⏳ Waiting for configuration to be completed..."
	@echo "   Please configure your settings in the web interface."
	@echo "   The setup will automatically continue once configuration is saved."
	@while ! docker-compose -f docker-compose-cpu.yml exec -T init-ui test -f /project/.env || \
	       ! docker-compose -f docker-compose-cpu.yml exec -T init-ui grep -q "^COMPOSE_PROFILES=app" /project/.env 2>/dev/null; do \
		echo "   Still waiting for configuration... (checking every 5 seconds)"; \
		sleep 5; \
	done
	@echo "✅ Configuration completed!"
	@echo "🚀 Starting OpenRAG application stack..."
	docker-compose -f docker-compose-cpu.yml --profile app up -d --wait
	@echo "✅ OpenRAG is now running!"
	@echo "   Backend: http://localhost:8000"
	@echo "   Frontend: http://localhost:3000"
	@echo "   Langflow: http://localhost:7860"
	@echo "   OpenSearch: http://localhost:9200"
	@echo "   Dashboards: http://localhost:5601"
	@echo "🔄 Stopping setup container..."
	docker-compose -f docker-compose-cpu.yml down init-ui