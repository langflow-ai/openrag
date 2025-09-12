# Configuration

OpenRAG uses environment variables for configuration. Copy `.env.example` to `.env` and populate with your values:

```bash
cp .env.example .env
```

## Required Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Your OpenAI API key |
| `OPENSEARCH_PASSWORD` | Password for OpenSearch admin user |
| `LANGFLOW_SUPERUSER` | Langflow admin username |
| `LANGFLOW_SUPERUSER_PASSWORD` | Langflow admin password |
| `LANGFLOW_CHAT_FLOW_ID` | ID of your Langflow chat flow |
| `LANGFLOW_INGEST_FLOW_ID` | ID of your Langflow ingestion flow |
| `NUDGES_FLOW_ID` | ID of your Langflow nudges/suggestions flow |

## Ingestion Configuration

| Variable | Description |
|----------|-------------|
| `DISABLE_INGEST_WITH_LANGFLOW` | Disable Langflow ingestion pipeline (default: `false`) |

- `false` or unset: Uses Langflow pipeline (upload → ingest → delete)
- `true`: Uses traditional OpenRAG processor for document ingestion

## Optional Variables

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

See `.env.example` for a complete list with descriptions, and `docker-compose*.yml` for runtime usage.
