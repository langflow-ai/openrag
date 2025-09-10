# OpenRAG

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/phact/openrag)

OpenRAG is a comprehensive Retrieval-Augmented Generation platform that enables intelligent document search and AI-powered conversations. Users can upload, process, and query documents through a chat interface backed by large language models and semantic search capabilities. The system utilizes Langflow for document ingestion, retrieval workflows, and intelligent nudges, providing a seamless RAG experience. Built with Starlette, Next.js, OpenSearch, and Langflow integration.

## 📋 Table of Contents

- [Quick Start](#quick-start)
- [TUI Interface](#tui-interface)
- [Configuration](#configuration)
- [Docker Deployment](#docker-deployment)
- [Development](#development)
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

## 🖥️ TUI Interface

OpenRAG includes a powerful Terminal User Interface (TUI) for easy setup, configuration, and monitoring. The TUI provides a user-friendly way to manage your OpenRAG installation without complex command-line operations.

![OpenRAG TUI Interface](assets/OpenRAG_TUI_2025-09-10T13_04_11_757637.svg)

### Launching the TUI

```bash
# Install dependencies first
uv sync

# Launch the TUI
uv run openrag
```

### TUI Features

The TUI provides several screens and capabilities:

#### Welcome Screen
- **Quick Setup Options**: Choose between basic setup (no authentication) or advanced setup (with OAuth)
- **Service Monitoring**: Check if containers are running and their status
- **Quick Actions**: Access diagnostics, logs, and configuration screens

#### Configuration Screen
- **Environment Variables**: Easy-to-use forms for setting up required configuration
- **API Keys**: Secure input for OpenAI API keys with validation
- **OAuth Setup**: Configure Google and Microsoft authentication
- **Document Paths**: Set up document ingestion directories
- **Auto-Save**: Automatically generates and saves `.env` file

#### Service Monitor
- **Container Status**: Real-time view of all OpenRAG services
- **Resource Usage**: Monitor CPU, memory, and network usage
- **Service Control**: Start, stop, and restart individual services
- **Health Checks**: Built-in health monitoring for all components

#### Log Viewer
- **Real-time Logs**: Live streaming of container logs
- **Service Filtering**: View logs for specific services (backend, frontend, Langflow, OpenSearch)
- **Log Levels**: Filter by log levels (DEBUG, INFO, WARNING, ERROR)
- **Export Options**: Save logs to files for analysis

#### Diagnostics
- **System Check**: Verify Docker/Podman installation and configuration
- **Environment Validation**: Check required environment variables
- **Network Testing**: Test connectivity between services
- **Performance Metrics**: System resource availability and recommendations

### TUI Navigation

- **Arrow Keys**: Navigate between options and screens
- **Tab/Shift+Tab**: Move between form fields and buttons
- **Enter**: Select/activate options
- **Escape**: Go back to previous screen
- **Q**: Quit the application
- **Number Keys (1-4)**: Quick access to main screens from welcome

### Benefits of Using the TUI

1. **Simplified Setup**: No need to manually edit configuration files
2. **Visual Feedback**: Clear status indicators and error messages
3. **Integrated Monitoring**: Everything in one interface
4. **Cross-Platform**: Works on Linux, macOS, and Windows
5. **No Browser Required**: Fully terminal-based interface


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



## 🛠️ Development

For developers wanting to contribute to OpenRAG or set up a development environment, please see our comprehensive development guide:

**[📚 See CONTRIBUTING.md for detailed development instructions](CONTRIBUTING.md)**

The contributing guide includes:
- Complete development environment setup
- Local development workflows  
- Testing and debugging procedures
- Code style guidelines
- Architecture overview
- Pull request guidelines

### Quick Development Commands

```bash
make help                    # See all available commands
make setup                   # Initial development setup
make infra                   # Start infrastructure services
make backend                 # Run backend locally
make frontend                # Run frontend locally
```