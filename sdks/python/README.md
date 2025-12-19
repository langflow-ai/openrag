# OpenRAG Python SDK

Official Python SDK for the [OpenRAG](https://openr.ag) API.

## Installation

```bash
pip install openrag-sdk
```

## Quick Start

```python
import asyncio
from openrag_sdk import OpenRAGClient

async def main():
    # Client auto-discovers OPENRAG_API_KEY and OPENRAG_URL from environment
    async with OpenRAGClient() as client:
        # Simple chat
        response = await client.chat.create(message="What is RAG?")
        print(response.response)
        print(f"Chat ID: {response.chat_id}")

asyncio.run(main())
```

## Configuration

The SDK can be configured via environment variables or constructor arguments:

| Environment Variable | Constructor Argument | Description |
|---------------------|---------------------|-------------|
| `OPENRAG_API_KEY` | `api_key` | API key for authentication (required) |
| `OPENRAG_URL` | `base_url` | Base URL for the OpenRAG frontend (default: `http://localhost:3000`) |

```python
# Using environment variables
client = OpenRAGClient()

# Using explicit arguments
client = OpenRAGClient(
    api_key="orag_...",
    base_url="https://api.example.com"
)
```

## Chat

### Non-streaming

```python
response = await client.chat.create(message="What is RAG?")
print(response.response)
print(f"Chat ID: {response.chat_id}")

# Continue conversation
followup = await client.chat.create(
    message="Tell me more",
    chat_id=response.chat_id
)
```

### Streaming with `create(stream=True)`

Returns an async iterator directly:

```python
chat_id = None
async for event in await client.chat.create(message="Explain RAG", stream=True):
    if event.type == "content":
        print(event.delta, end="", flush=True)
    elif event.type == "sources":
        for source in event.sources:
            print(f"\nSource: {source.filename}")
    elif event.type == "done":
        chat_id = event.chat_id
```

### Streaming with `stream()` Context Manager

Provides additional helpers for convenience:

```python
# Full event iteration
async with client.chat.stream(message="Explain RAG") as stream:
    async for event in stream:
        if event.type == "content":
            print(event.delta, end="", flush=True)

    # Access aggregated data after iteration
    print(f"\nChat ID: {stream.chat_id}")
    print(f"Full text: {stream.text}")
    print(f"Sources: {stream.sources}")

# Just text deltas
async with client.chat.stream(message="Explain RAG") as stream:
    async for text in stream.text_stream:
        print(text, end="", flush=True)

# Get final text directly
async with client.chat.stream(message="Explain RAG") as stream:
    text = await stream.final_text()
    print(text)
```

### Conversation History

```python
# List all conversations
conversations = await client.chat.list()
for conv in conversations.conversations:
    print(f"{conv.chat_id}: {conv.title}")

# Get specific conversation with messages
conversation = await client.chat.get(chat_id)
for msg in conversation.messages:
    print(f"{msg.role}: {msg.content}")

# Delete conversation
await client.chat.delete(chat_id)
```

## Search

```python
# Basic search
results = await client.search.query("document processing")
for result in results.results:
    print(f"{result.filename} (score: {result.score})")
    print(f"  {result.text[:100]}...")

# Search with filters
from openrag_sdk import SearchFilters

results = await client.search.query(
    "API documentation",
    filters=SearchFilters(
        data_sources=["api-docs.pdf"],
        document_types=["application/pdf"]
    ),
    limit=5,
    score_threshold=0.5
)
```

## Documents

```python
# Ingest a file (waits for completion by default)
result = await client.documents.ingest(file_path="./report.pdf")
print(f"Status: {result.status}")
print(f"Successful files: {result.successful_files}")

# Ingest without waiting (returns immediately with task_id)
result = await client.documents.ingest(file_path="./report.pdf", wait=False)
print(f"Task ID: {result.task_id}")

# Poll for completion manually
final_status = await client.documents.wait_for_task(result.task_id)
print(f"Status: {final_status.status}")
print(f"Successful files: {final_status.successful_files}")

# Ingest from file object
with open("./report.pdf", "rb") as f:
    result = await client.documents.ingest(file=f, filename="report.pdf")

# Delete a document
result = await client.documents.delete("report.pdf")
print(f"Success: {result.success}")
```

## Settings

```python
# Get settings
settings = await client.settings.get()
print(f"LLM Provider: {settings.agent.llm_provider}")
print(f"LLM Model: {settings.agent.llm_model}")
print(f"Embedding Model: {settings.knowledge.embedding_model}")

# Update settings
await client.settings.update({
    "chunk_size": 1000,
    "chunk_overlap": 200,
})
```

## Knowledge Filters

Knowledge filters are reusable, named filter configurations that can be applied to chat and search operations.

```python
# Create a knowledge filter
result = await client.knowledge_filters.create({
    "name": "Technical Docs",
    "description": "Filter for technical documentation",
    "queryData": {
        "query": "technical",
        "filters": {
            "document_types": ["application/pdf"],
        },
        "limit": 10,
        "scoreThreshold": 0.5,
    },
})
filter_id = result.id

# Search for filters
filters = await client.knowledge_filters.search("Technical")
for f in filters:
    print(f"{f.name}: {f.description}")

# Get a specific filter
filter_obj = await client.knowledge_filters.get(filter_id)

# Update a filter
await client.knowledge_filters.update(filter_id, {
    "description": "Updated description",
})

# Delete a filter
await client.knowledge_filters.delete(filter_id)

# Use filter in chat
response = await client.chat.create(
    message="Explain the API",
    filter_id=filter_id,
)

# Use filter in search
results = await client.search.query("API endpoints", filter_id=filter_id)
```

## Error Handling

```python
from openrag_sdk import (
    OpenRAGError,
    AuthenticationError,
    NotFoundError,
    ValidationError,
    RateLimitError,
    ServerError,
)

try:
    response = await client.chat.create(message="Hello")
except AuthenticationError as e:
    print(f"Invalid API key: {e.message}")
except NotFoundError as e:
    print(f"Resource not found: {e.message}")
except ValidationError as e:
    print(f"Invalid request: {e.message}")
except RateLimitError as e:
    print(f"Rate limited: {e.message}")
except ServerError as e:
    print(f"Server error: {e.message}")
except OpenRAGError as e:
    print(f"API error: {e.message} (status: {e.status_code})")
```

## License

MIT
