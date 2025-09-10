## OpenRAG

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/phact/openrag)

### getting started

Set up your secrets:

    cp .env.example .env

Populate the values in .env

Requirements:

Docker or podman with compose installed.

Run OpenRAG:

    docker compose build

    docker compose up

CPU only:

    docker compose -f docker-compose-cpu.yml up

If you need to reset state:

    docker compose up --build --force-recreate --remove-orphans

### Configuration

OpenRAG uses environment variables for configuration. Copy `.env.example` to `.env` and populate with your values:

```bash
cp .env.example .env
```

#### Key Environment Variables

**Required:**
- `OPENAI_API_KEY`: Your OpenAI API key
- `OPENSEARCH_PASSWORD`: Password for OpenSearch admin user
- `LANGFLOW_SUPERUSER`: Langflow admin username  
- `LANGFLOW_SUPERUSER_PASSWORD`: Langflow admin password
- `LANGFLOW_CHAT_FLOW_ID`: ID of your Langflow chat flow
- `LANGFLOW_INGEST_FLOW_ID`: ID of your Langflow ingestion flow
- `NUDGES_FLOW_ID`: ID of your Langflow nudges/suggestions flow

**Ingestion Configuration:**
- `DISABLE_INGEST_WITH_LANGFLOW`: Disable Langflow ingestion pipeline (default: `false`)
  - `false` or unset: Uses Langflow pipeline (upload → ingest → delete)
  - `true`: Uses traditional OpenRAG processor for document ingestion

**Optional:**
- `LANGFLOW_PUBLIC_URL`: Public URL for Langflow (default: `http://localhost:7860`)
- `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`: For Google OAuth authentication
- `MICROSOFT_GRAPH_OAUTH_CLIENT_ID` / `MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET`: For Microsoft OAuth
- `WEBHOOK_BASE_URL`: Base URL for webhook endpoints
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`: For AWS integrations
- `SESSION_SECRET`: Secret key for session management (default: auto-generated, change in production)
- `LANGFLOW_KEY`: Explicit Langflow API key (auto-generated if not provided)
- `LANGFLOW_SECRET_KEY`: Secret key for Langflow internal operations

See `.env.example` for a complete list with descriptions, or check the docker-compose.yml files.

For podman on mac you may have to increase your VM memory (`podman stats` should not show limit at only 2gb):

    podman machine stop
    podman machine rm
    podman machine init --memory 8192   # example: 8 GB
    podman machine start
