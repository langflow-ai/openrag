---
title: Environment variables and configuration values
slug: /configure/configuration
---

OpenRAG supports multiple configuration methods with the following priority:

1. **Environment Variables** (highest priority)
2. **Configuration File** (`config.yaml`)
3. **Default Values** (fallback)

## Environment variables

Environment variables will override configuration file settings.
You can create a `.env` file in the project root to set these variables.

## Required variables

| Variable                      | Description                                 |
| ----------------------------- | ------------------------------------------- |
| `OPENAI_API_KEY`              | Your OpenAI API key                         |
| `OPENSEARCH_PASSWORD`         | Password for OpenSearch admin user          |
| `LANGFLOW_SUPERUSER`          | Langflow admin username                     |
| `LANGFLOW_SUPERUSER_PASSWORD` | Langflow admin password                     |
| `LANGFLOW_CHAT_FLOW_ID`       | ID of your Langflow chat flow               |
| `LANGFLOW_INGEST_FLOW_ID`     | ID of your Langflow ingestion flow          |
| `NUDGES_FLOW_ID`              | ID of your Langflow nudges/suggestions flow |

## Ingestion configuration

| Variable                       | Description                                            |
| ------------------------------ | ------------------------------------------------------ |
| `DISABLE_INGEST_WITH_LANGFLOW` | Disable Langflow ingestion pipeline (default: `false`) |

- `false` or unset: Uses Langflow pipeline (upload → ingest → delete)
- `true`: Uses traditional OpenRAG processor for document ingestion

## Optional variables

| Variable                                                                  | Description                                                        |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `OPENSEARCH_HOST`                                                         | OpenSearch host (default: `localhost`)                             |
| `OPENSEARCH_PORT`                                                         | OpenSearch port (default: `9200`)                                  |
| `OPENSEARCH_USERNAME`                                                     | OpenSearch username (default: `admin`)                            |
| `LANGFLOW_URL`                                                            | Langflow URL (default: `http://localhost:7860`)                    |
| `LANGFLOW_PUBLIC_URL`                                                     | Public URL for Langflow (default: `http://localhost:7860`)         |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`                   | Google OAuth authentication                                        |
| `MICROSOFT_GRAPH_OAUTH_CLIENT_ID` / `MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET` | Microsoft OAuth                                                    |
| `WEBHOOK_BASE_URL`                                                        | Base URL for webhook endpoints                                     |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`                             | AWS integrations                                                   |
| `SESSION_SECRET`                                                          | Session management (default: auto-generated, change in production) |
| `LANGFLOW_KEY`                                                            | Explicit Langflow API key (auto-generated if not provided)         |
| `LANGFLOW_SECRET_KEY`                                                     | Secret key for Langflow internal operations                        |
| `DOCLING_OCR_ENGINE`                                                      | OCR engine for document processing                                |
| `LANGFLOW_AUTO_LOGIN`                                                     | Enable auto-login for Langflow (default: `False`)                 |
| `LANGFLOW_NEW_USER_IS_ACTIVE`                                             | New users are active by default (default: `False`)                 |
| `LANGFLOW_ENABLE_SUPERUSER_CLI`                                           | Enable superuser CLI (default: `False`)                            |
| `OPENRAG_DOCUMENTS_PATHS`                                                 | Document paths for ingestion (default: `./documents`)              |

## OpenRAG configuration variables

These environment variables override settings in `config.yaml`:

### Provider settings

| Variable             | Description                              | Default  |
| -------------------- | ---------------------------------------- | -------- |
| `MODEL_PROVIDER`     | Model provider (openai, anthropic, etc.) | `openai` |
| `PROVIDER_API_KEY`   | API key for the model provider           |          |
| `PROVIDER_ENDPOINT`  | Custom provider endpoint (e.g., Watson)  |          |
| `PROVIDER_PROJECT_ID`| Project ID for providers (e.g., Watson)  |          |
| `OPENAI_API_KEY`     | OpenAI API key (backward compatibility)  |          |

### Knowledge settings

| Variable                       | Description                             | Default                  |
| ------------------------------ | --------------------------------------- | ------------------------ |
| `EMBEDDING_MODEL`              | Embedding model for vector search       | `text-embedding-3-small` |
| `CHUNK_SIZE`                   | Text chunk size for document processing | `1000`                   |
| `CHUNK_OVERLAP`                | Overlap between chunks                  | `200`                    |
| `OCR_ENABLED`                  | Enable OCR for image processing         | `true`                   |
| `PICTURE_DESCRIPTIONS_ENABLED` | Enable picture descriptions             | `false`                  |

### Agent settings

| Variable        | Description                       | Default                  |
| --------------- | --------------------------------- | ------------------------ |
| `LLM_MODEL`     | Language model for the chat agent | `gpt-4o-mini`            |
| `SYSTEM_PROMPT` | System prompt for the agent       | "You are a helpful AI assistant with access to a knowledge base. Answer questions based on the provided context." |

See `docker-compose-*.yml` files for runtime usage examples.

## Configuration file

Create a `config.yaml` file in the project root to configure OpenRAG:

```yaml
# OpenRAG Configuration File
provider:
  model_provider: "openai" # openai, anthropic, azure, etc.
  api_key: "your-api-key" # or use OPENAI_API_KEY env var
  endpoint: "" # For custom provider endpoints (e.g., Watson/IBM)
  project_id: "" # For providers that need project IDs (e.g., Watson/IBM)

knowledge:
  embedding_model: "text-embedding-3-small"
  chunk_size: 1000
  chunk_overlap: 200
  doclingPresets: "standard" # standard, ocr, picture_description, VLM
  ocr: true
  picture_descriptions: false

agent:
  llm_model: "gpt-4o-mini"
  system_prompt: "You are a helpful AI assistant with access to a knowledge base. Answer questions based on the provided context."
```

## Default Values and Fallbacks

When no environment variables or configuration file values are provided, OpenRAG uses default values.
These values can be found in the code base at the following locations.

### OpenRAG configuration defaults

These values are are defined in `src/config/config_manager.py`.

### System configuration defaults

These fallback values are defined in `src/config/settings.py`.

### TUI default values

These values are defined in `src/tui/managers/env_manager.py`.

### Frontend default values

These values are defined in `frontend/src/lib/constants.ts`.

### Docling preset configurations

These values are defined in `src/api/settings.py`.