# Configuration

OpenRAG supports multiple configuration methods with the following priority:

1. **Environment Variables** (highest priority)
2. **Configuration File** (`config.yaml`)
3. **Langflow Flow Settings** (runtime override)
4. **Default Values** (fallback)

## Configuration File

Create a `config.yaml` file in the project root to configure OpenRAG:

```yaml
# OpenRAG Configuration File
provider:
  model_provider: "openai" # openai, anthropic, azure, etc.
  api_key: "your-api-key" # or use OPENAI_API_KEY env var

knowledge:
  embedding_model: "text-embedding-3-small"
  chunk_size: 1000
  chunk_overlap: 200
  ocr: true
  picture_descriptions: false

agent:
  llm_model: "gpt-4o-mini"
  system_prompt: "You are a helpful AI assistant..."
```

## Environment Variables

Environment variables will override configuration file settings. You can still use `.env` files:

```bash
cp .env.example .env
```

## Required Variables

| Variable                      | Description                                 |
| ----------------------------- | ------------------------------------------- |
| `OPENAI_API_KEY`              | Your OpenAI API key                         |
| `OPENSEARCH_PASSWORD`         | Password for OpenSearch admin user          |
| `LANGFLOW_SUPERUSER`          | Langflow admin username                     |
| `LANGFLOW_SUPERUSER_PASSWORD` | Langflow admin password                     |
| `LANGFLOW_CHAT_FLOW_ID`       | ID of your Langflow chat flow               |
| `LANGFLOW_INGEST_FLOW_ID`     | ID of your Langflow ingestion flow          |
| `NUDGES_FLOW_ID`              | ID of your Langflow nudges/suggestions flow |

## Ingestion Configuration

| Variable                       | Description                                            |
| ------------------------------ | ------------------------------------------------------ |
| `DISABLE_INGEST_WITH_LANGFLOW` | Disable Langflow ingestion pipeline (default: `false`) |

- `false` or unset: Uses Langflow pipeline (upload → ingest → delete)
- `true`: Uses traditional OpenRAG processor for document ingestion

## Optional Variables

| Variable                                                                  | Description                                                        |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `LANGFLOW_PUBLIC_URL`                                                     | Public URL for Langflow (default: `http://localhost:7860`)         |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`                   | Google OAuth authentication                                        |
| `MICROSOFT_GRAPH_OAUTH_CLIENT_ID` / `MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET` | Microsoft OAuth                                                    |
| `WEBHOOK_BASE_URL`                                                        | Base URL for webhook endpoints                                     |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`                             | AWS integrations                                                   |
| `SESSION_SECRET`                                                          | Session management (default: auto-generated, change in production) |
| `LANGFLOW_KEY`                                                            | Explicit Langflow API key (auto-generated if not provided)         |
| `LANGFLOW_SECRET_KEY`                                                     | Secret key for Langflow internal operations                        |

## OpenRAG Configuration Variables

These environment variables override settings in `config.yaml`:

### Provider Settings

| Variable           | Description                              | Default  |
| ------------------ | ---------------------------------------- | -------- |
| `MODEL_PROVIDER`   | Model provider (openai, anthropic, etc.) | `openai` |
| `PROVIDER_API_KEY` | API key for the model provider           |          |
| `OPENAI_API_KEY`   | OpenAI API key (backward compatibility)  |          |

### Knowledge Settings

| Variable                       | Description                             | Default                  |
| ------------------------------ | --------------------------------------- | ------------------------ |
| `EMBEDDING_MODEL`              | Embedding model for vector search       | `text-embedding-3-small` |
| `CHUNK_SIZE`                   | Text chunk size for document processing | `1000`                   |
| `CHUNK_OVERLAP`                | Overlap between chunks                  | `200`                    |
| `OCR_ENABLED`                  | Enable OCR for image processing         | `true`                   |
| `PICTURE_DESCRIPTIONS_ENABLED` | Enable picture descriptions             | `false`                  |

### Agent Settings

| Variable        | Description                       | Default                  |
| --------------- | --------------------------------- | ------------------------ |
| `LLM_MODEL`     | Language model for the chat agent | `gpt-4o-mini`            |
| `SYSTEM_PROMPT` | System prompt for the agent       | Default assistant prompt |

See `.env.example` for a complete list with descriptions, and `docker-compose*.yml` for runtime usage.
