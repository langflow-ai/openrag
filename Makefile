# OpenRAG Development Makefile
# Provides easy commands for development workflow

# Load variables from .env if present so `make` commands pick them up
# Strip quotes from values to avoid issues with tools that don't handle them like python-dotenv does
ifneq (,$(wildcard .env))
  include .env
  export $(shell sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' .env)
  # Strip single quotes from all exported variables
  $(foreach var,$(shell sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' .env),$(eval $(var):=$(shell echo $($(var)) | sed "s/^'//;s/'$$//")))
endif

.PHONY: help dev dev-cpu dev-local infra stop clean build logs shell-backend shell-frontend install \
       test test-integration test-ci test-ci-local test-sdk \
       backend frontend install-be install-fe build-be build-fe logs-be logs-fe logs-lf logs-os \
       shell-be shell-lf shell-os restart status health db-reset flow-upload quick setup

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
	@echo "  test             - Run all backend tests"
	@echo "  test-integration - Run integration tests (requires infra)"
	@echo "  test-ci          - Start infra, run integration + SDK tests, tear down (uses DockerHub images)"
	@echo "  test-ci-local    - Same as test-ci but builds all images locally"
	@echo "  test-sdk         - Run SDK integration tests (requires running OpenRAG at localhost:3000)"
	@echo "  lint         - Run linting checks"
	@echo ""

# Development environments
dev:
	@echo "🚀 Starting OpenRAG with GPU support..."
	docker compose up -d
	@echo "✅ Services started!"
	@echo "   Backend: http://localhost:8000"
	@echo "   Frontend: http://localhost:3000"
	@echo "   Langflow: http://localhost:7860"
	@echo "   OpenSearch: http://localhost:9200"
	@echo "   Dashboards: http://localhost:5601"

dev-cpu:
	@echo "🚀 Starting OpenRAG with CPU only..."
	docker compose -f docker-compose-cpu.yml up -d
	@echo "✅ Services started!"
	@echo "   Backend: http://localhost:8000"
	@echo "   Frontend: http://localhost:3000"
	@echo "   Langflow: http://localhost:7860"
	@echo "   OpenSearch: http://localhost:9200"
	@echo "   Dashboards: http://localhost:5601"

dev-local:
	@echo "🔧 Starting infrastructure only (for local development)..."
	docker compose up -d opensearch dashboards langflow
	@echo "✅ Infrastructure started!"
	@echo "   Langflow: http://localhost:7860"
	@echo "   OpenSearch: http://localhost:9200"
	@echo "   Dashboards: http://localhost:5601"
	@echo ""
	@echo "Now run 'make backend' and 'make frontend' in separate terminals"

infra:
	@echo "🔧 Starting infrastructure services only..."
	docker compose up -d opensearch dashboards langflow
	@echo "✅ Infrastructure services started!"
	@echo "   Langflow: http://localhost:7860"
	@echo "   OpenSearch: http://localhost:9200"
	@echo "   Dashboards: http://localhost:5601"

infra-cpu:
	@echo "🔧 Starting infrastructure services only..."
	docker-compose -f docker-compose-cpu.yml up -d opensearch dashboards langflow
	@echo "✅ Infrastructure services started!"
	@echo "   Langflow: http://localhost:7860"
	@echo "   OpenSearch: http://localhost:9200"
	@echo "   Dashboards: http://localhost:5601"

# Container management
stop:
	@echo "🛑 Stopping all containers..."
	docker compose down
	docker compose -f docker-compose-cpu.yml down 2>/dev/null || true

restart: stop dev

clean: stop
	@echo "🧹 Cleaning up containers and volumes..."
	docker compose down -v --remove-orphans
	docker compose -f docker-compose-cpu.yml down -v --remove-orphans 2>/dev/null || true
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
	uv sync --extra torch-cu128

install-fe:
	@echo "📦 Installing frontend dependencies..."
	cd frontend && npm install

# Building
build:
	@echo "Building all Docker images locally..."
	docker build -t langflowai/openrag-opensearch:latest -f Dockerfile .
	docker build -t langflowai/openrag-backend:latest -f Dockerfile.backend .
	docker build -t langflowai/openrag-frontend:latest -f Dockerfile.frontend .
	docker build -t langflowai/openrag-langflow:latest -f Dockerfile.langflow .

build-be:
	@echo "Building backend image..."
	docker build -t langflowai/openrag-backend:latest -f Dockerfile.backend .

build-fe:
	@echo "Building frontend image..."
	docker build -t langflowai/openrag-frontend:latest -f Dockerfile.frontend .

# Logging and debugging
logs:
	@echo "📋 Showing all container logs..."
	docker compose logs -f

logs-be:
	@echo "📋 Showing backend logs..."
	docker compose logs -f openrag-backend

logs-fe:
	@echo "📋 Showing frontend logs..."
	docker compose logs -f openrag-frontend

logs-lf:
	@echo "📋 Showing langflow logs..."
	docker compose logs -f langflow

logs-os:
	@echo "📋 Showing opensearch logs..."
	docker compose logs -f opensearch

# Shell access
shell-be:
	@echo "🐚 Opening shell in backend container..."
	docker compose exec openrag-backend /bin/bash

shell-lf:
	@echo "🐚 Opening shell in langflow container..."
	docker compose exec langflow /bin/bash

shell-os:
	@echo "🐚 Opening shell in opensearch container..."
	docker compose exec opensearch /bin/bash

# Testing and quality
test:
	@echo "🧪 Running all backend tests..."
	uv run pytest tests/ -v

test-integration:
	@echo "🧪 Running integration tests (requires infrastructure)..."
	@echo "💡 Make sure to run 'make infra' first!"
	uv run pytest tests/integration/ -v

# CI-friendly integration test target: brings up infra, waits, runs tests, tears down
test-ci:
	@set -e; \
	echo "Installing test dependencies..."; \
	uv sync --group dev; \
	if [ ! -f keys/private_key.pem ]; then \
		echo "Generating RSA keys for JWT signing..."; \
		uv run python -c "from src.main import generate_jwt_keys; generate_jwt_keys()"; \
	else \
		echo "RSA keys already exist, ensuring correct permissions..."; \
		chmod 600 keys/private_key.pem 2>/dev/null || true; \
		chmod 644 keys/public_key.pem 2>/dev/null || true; \
	fi; \
	echo "Cleaning up old containers and volumes..."; \
	docker compose -f docker-compose-cpu.yml down -v 2>/dev/null || true; \
	echo "Pulling latest images..."; \
	docker compose -f docker-compose-cpu.yml pull; \
	echo "Building OpenSearch image override..."; \
	docker build --no-cache -t langflowai/openrag-opensearch:latest -f Dockerfile .; \
	echo "Starting infra (OpenSearch + Dashboards + Langflow + Backend + Frontend) with CPU containers"; \
	docker compose -f docker-compose-cpu.yml up -d opensearch dashboards langflow openrag-backend openrag-frontend; \
	echo "Starting docling-serve..."; \
	DOCLING_ENDPOINT=$$(uv run python scripts/docling_ctl.py start --port 5001 | grep "Endpoint:" | awk '{print $$2}'); \
	echo "Docling-serve started at $$DOCLING_ENDPOINT"; \
	echo "Waiting for backend OIDC endpoint..."; \
	for i in $$(seq 1 60); do \
		docker exec openrag-backend curl -s http://localhost:8000/.well-known/openid-configuration >/dev/null 2>&1 && break || sleep 2; \
	done; \
	echo "Waiting for OpenSearch security config to be fully applied..."; \
	for i in $$(seq 1 60); do \
		if docker logs os 2>&1 | grep -q "Security configuration applied successfully"; then \
			echo "✓ Security configuration applied"; \
			break; \
		fi; \
		sleep 2; \
	done; \
	echo "Verifying OIDC authenticator is active in OpenSearch..."; \
	AUTHC_CONFIG=$$(curl -k -s -u admin:$${OPENSEARCH_PASSWORD} https://localhost:9200/_opendistro/_security/api/securityconfig 2>/dev/null); \
	if echo "$$AUTHC_CONFIG" | grep -q "openid_auth_domain"; then \
		echo "✓ OIDC authenticator configured"; \
		echo "$$AUTHC_CONFIG" | grep -A 5 "openid_auth_domain"; \
	else \
		echo "✗ OIDC authenticator NOT found in security config!"; \
		echo "Security config:"; \
		echo "$$AUTHC_CONFIG" | head -50; \
		exit 1; \
	fi; \
	echo "Waiting for Langflow..."; \
	for i in $$(seq 1 60); do \
		curl -s http://localhost:7860/ >/dev/null 2>&1 && break || sleep 2; \
	done; \
	echo "Waiting for docling-serve at $$DOCLING_ENDPOINT..."; \
	for i in $$(seq 1 60); do \
		curl -s $${DOCLING_ENDPOINT}/health >/dev/null 2>&1 && break || sleep 2; \
	done; \
	echo "Running integration tests"; \
	LOG_LEVEL=$${LOG_LEVEL:-DEBUG} \
	GOOGLE_OAUTH_CLIENT_ID="" \
	GOOGLE_OAUTH_CLIENT_SECRET="" \
	OPENSEARCH_HOST=localhost OPENSEARCH_PORT=9200 \
	OPENSEARCH_USERNAME=admin OPENSEARCH_PASSWORD=$${OPENSEARCH_PASSWORD} \
	DISABLE_STARTUP_INGEST=$${DISABLE_STARTUP_INGEST:-true} \
	uv run pytest tests/integration -vv -s -o log_cli=true --log-cli-level=DEBUG; \
	TEST_RESULT=$$?; \
	echo ""; \
	echo "Waiting for frontend at http://localhost:3000..."; \
	for i in $$(seq 1 60); do \
		curl -s http://localhost:3000/ >/dev/null 2>&1 && break || sleep 2; \
	done; \
	echo "Running Python SDK integration tests"; \
	cd sdks/python && \
	uv pip install -e ".[dev]" && \
	OPENRAG_URL=http://localhost:3000 uv run pytest tests/test_integration.py -vv -s || TEST_RESULT=1; \
	cd ../..; \
	echo "Running TypeScript SDK integration tests"; \
	cd sdks/typescript && \
	npm install && npm run build && \
	OPENRAG_URL=http://localhost:3000 npm test || TEST_RESULT=1; \
	cd ../..; \
	echo ""; \
	echo "=== Post-test JWT diagnostics ==="; \
	echo "Generating test JWT token..."; \
	TEST_TOKEN=$$(uv run python -c "from src.session_manager import SessionManager, AnonymousUser; sm = SessionManager('test'); print(sm.create_jwt_token(AnonymousUser()))" 2>/dev/null || echo ""); \
	if [ -n "$$TEST_TOKEN" ]; then \
		echo "Testing JWT against OpenSearch..."; \
		HTTP_CODE=$$(curl -k -s -w "%{http_code}" -o /tmp/os_diag.txt -H "Authorization: Bearer $$TEST_TOKEN" -H "Content-Type: application/json" https://localhost:9200/documents/_search -d '{"query":{"match_all":{}}}' 2>&1); \
		echo "HTTP $$HTTP_CODE: $$(cat /tmp/os_diag.txt | head -c 150)"; \
	fi; \
	echo "================================="; \
	echo ""; \
	echo "Tearing down infra"; \
	uv run python scripts/docling_ctl.py stop || true; \
	docker compose -f docker-compose-cpu.yml down -v 2>/dev/null || true; \
	exit $$TEST_RESULT

# CI-friendly integration test target with local builds: builds all images, brings up infra, waits, runs tests, tears down
test-ci-local:
	@set -e; \
	echo "Installing test dependencies..."; \
	uv sync --group dev; \
	if [ ! -f keys/private_key.pem ]; then \
		echo "Generating RSA keys for JWT signing..."; \
		uv run python -c "from src.main import generate_jwt_keys; generate_jwt_keys()"; \
	else \
		echo "RSA keys already exist, ensuring correct permissions..."; \
		chmod 600 keys/private_key.pem 2>/dev/null || true; \
		chmod 644 keys/public_key.pem 2>/dev/null || true; \
	fi; \
	echo "Cleaning up old containers and volumes..."; \
	docker compose -f docker-compose-cpu.yml down -v 2>/dev/null || true; \
	echo "Building all images locally..."; \
	docker build -t langflowai/openrag-opensearch:latest -f Dockerfile .; \
	docker build -t langflowai/openrag-backend:latest -f Dockerfile.backend .; \
	docker build -t langflowai/openrag-frontend:latest -f Dockerfile.frontend .; \
	docker build -t langflowai/openrag-langflow:latest -f Dockerfile.langflow .; \
	echo "Starting infra (OpenSearch + Dashboards + Langflow + Backend + Frontend) with CPU containers"; \
	docker compose -f docker-compose-cpu.yml up -d opensearch dashboards langflow openrag-backend openrag-frontend; \
	echo "Starting docling-serve..."; \
	DOCLING_ENDPOINT=$$(uv run python scripts/docling_ctl.py start --port 5001 | grep "Endpoint:" | awk '{print $$2}'); \
	echo "Docling-serve started at $$DOCLING_ENDPOINT"; \
	echo "Waiting for backend OIDC endpoint..."; \
	for i in $$(seq 1 60); do \
		docker exec openrag-backend curl -s http://localhost:8000/.well-known/openid-configuration >/dev/null 2>&1 && break || sleep 2; \
	done; \
	echo "Waiting for OpenSearch security config to be fully applied..."; \
	for i in $$(seq 1 60); do \
		if docker logs os 2>&1 | grep -q "Security configuration applied successfully"; then \
			echo "✓ Security configuration applied"; \
			break; \
		fi; \
		sleep 2; \
	done; \
	echo "Verifying OIDC authenticator is active in OpenSearch..."; \
	AUTHC_CONFIG=$$(curl -k -s -u admin:$${OPENSEARCH_PASSWORD} https://localhost:9200/_opendistro/_security/api/securityconfig 2>/dev/null); \
	if echo "$$AUTHC_CONFIG" | grep -q "openid_auth_domain"; then \
		echo "✓ OIDC authenticator configured"; \
		echo "$$AUTHC_CONFIG" | grep -A 5 "openid_auth_domain"; \
	else \
		echo "✗ OIDC authenticator NOT found in security config!"; \
		echo "Security config:"; \
		echo "$$AUTHC_CONFIG" | head -50; \
		exit 1; \
	fi; \
	echo "Waiting for Langflow..."; \
	for i in $$(seq 1 60); do \
		curl -s http://localhost:7860/ >/dev/null 2>&1 && break || sleep 2; \
	done; \
	echo "Waiting for docling-serve at $$DOCLING_ENDPOINT..."; \
	for i in $$(seq 1 60); do \
		curl -s $${DOCLING_ENDPOINT}/health >/dev/null 2>&1 && break || sleep 2; \
	done; \
	echo "Running integration tests"; \
	LOG_LEVEL=$${LOG_LEVEL:-DEBUG} \
	GOOGLE_OAUTH_CLIENT_ID="" \
	GOOGLE_OAUTH_CLIENT_SECRET="" \
	OPENSEARCH_HOST=localhost OPENSEARCH_PORT=9200 \
	OPENSEARCH_USERNAME=admin OPENSEARCH_PASSWORD=$${OPENSEARCH_PASSWORD} \
	DISABLE_STARTUP_INGEST=$${DISABLE_STARTUP_INGEST:-true} \
	uv run pytest tests/integration -vv -s -o log_cli=true --log-cli-level=DEBUG; \
	TEST_RESULT=$$?; \
	echo ""; \
	echo "Waiting for frontend at http://localhost:3000..."; \
	for i in $$(seq 1 60); do \
		curl -s http://localhost:3000/ >/dev/null 2>&1 && break || sleep 2; \
	done; \
	echo "Running Python SDK integration tests"; \
	cd sdks/python && \
	uv pip install -e ".[dev]" && \
	OPENRAG_URL=http://localhost:3000 uv run pytest tests/test_integration.py -vv -s || TEST_RESULT=1; \
	cd ../..; \
	echo "Running TypeScript SDK integration tests"; \
	cd sdks/typescript && \
	npm install && npm run build && \
	OPENRAG_URL=http://localhost:3000 npm test || TEST_RESULT=1; \
	cd ../..; \
	echo ""; \
	echo "=== Post-test JWT diagnostics ==="; \
	echo "Generating test JWT token..."; \
	TEST_TOKEN=$$(uv run python -c "from src.session_manager import SessionManager, AnonymousUser; sm = SessionManager('test'); print(sm.create_jwt_token(AnonymousUser()))" 2>/dev/null || echo ""); \
	if [ -n "$$TEST_TOKEN" ]; then \
		echo "Testing JWT against OpenSearch..."; \
		HTTP_CODE=$$(curl -k -s -w "%{http_code}" -o /tmp/os_diag.txt -H "Authorization: Bearer $$TEST_TOKEN" -H "Content-Type: application/json" https://localhost:9200/documents/_search -d '{"query":{"match_all":{}}}' 2>&1); \
		echo "HTTP $$HTTP_CODE: $$(cat /tmp/os_diag.txt | head -c 150)"; \
	fi; \
	echo "================================="; \
	echo ""; \
	echo "Tearing down infra"; \
	uv run python scripts/docling_ctl.py stop || true; \
	docker compose -f docker-compose-cpu.yml down -v 2>/dev/null || true; \
	exit $$TEST_RESULT

# SDK integration tests (requires running OpenRAG instance)
test-sdk:
	@echo "Running SDK integration tests..."
	@echo "Make sure OpenRAG backend is running at localhost:8000 (make backend)"
	@echo ""
	@echo "Running Python SDK tests..."
	cd sdks/python && uv pip install -e ".[dev]" && OPENRAG_URL=http://localhost:8000 uv run pytest tests/test_integration.py -vv -s
	@echo ""
	@echo "Running TypeScript SDK tests..."
	cd sdks/typescript && npm install && npm run build && OPENRAG_URL=http://localhost:8000 npm test

lint:
	@echo "🔍 Running linting checks..."
	cd frontend && npm run lint
	@echo "Frontend linting complete"

# Service status
status:
	@echo "📊 Container status:"
	@docker compose ps 2>/dev/null || echo "No containers running"

health:
	@echo "🏥 Health check:"
	@echo "Backend: $$(curl -s http://localhost:8000/health 2>/dev/null || echo 'Not responding')"
	@echo "Langflow: $$(curl -s http://localhost:7860/health 2>/dev/null || echo 'Not responding')"
	@echo "OpenSearch: $$(curl -s -k -u admin:$${OPENSEARCH_PASSWORD} https://localhost:9200 2>/dev/null | jq -r .tagline 2>/dev/null || echo 'Not responding')"

# Database operations
db-reset:
	@echo "🗄️ Resetting OpenSearch indices..."
	curl -X DELETE "http://localhost:9200/documents" -u admin:$${OPENSEARCH_PASSWORD} || true
	curl -X DELETE "http://localhost:9200/knowledge_filters" -u admin:$${OPENSEARCH_PASSWORD} || true
	@echo "Indices reset. Restart backend to recreate."

clear-os-data:
	@echo "🧹 Clearing OpenSearch data directory..."
	@uv run python scripts/clear_opensearch_data.py

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
