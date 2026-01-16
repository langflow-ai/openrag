# OpenRAG MCP Sequence Diagrams

This document illustrates the interaction flows between AI applications and OpenRAG through the Model Context Protocol (MCP) server.

## Participants

| Participant | Description |
|:------------|:------------|
| **AI App** | MCP-compatible application (Cursor IDE, Claude Desktop, Watson Orchestrate) |
| **MCP Server** | OpenRAG MCP server (`openrag-mcp`) running as subprocess |
| **OpenRAG SDK** | Python SDK client within MCP server |
| **OpenRAG API** | OpenRAG FastAPI backend server |
| **Knowledge Base** | OpenSearch vector database storing document embeddings |

---

## 1. Server Initialization

```mermaid
sequenceDiagram
    participant AIApp as AI Application
    participant MCP as MCP Server
    participant SDK as OpenRAG SDK
    participant API as OpenRAG API

    Note over AIApp,MCP: Startup Phase

    AIApp->>MCP: Spawn subprocess (uvx openrag-mcp)
    activate MCP
    MCP->>MCP: Load OPENRAG_API_KEY from env
    MCP->>MCP: Load OPENRAG_URL from env
    MCP->>SDK: Initialize client with credentials
    activate SDK
    SDK-->>MCP: Client ready
    deactivate SDK
    MCP->>MCP: Register tools (chat, search, ingest, delete)
    MCP-->>AIApp: Server initialized (stdio ready)

    Note over AIApp,MCP: Tool Discovery

    AIApp->>MCP: JSON-RPC: tools/list
    MCP-->>AIApp: Available tools array
```

---

## 2. Chat Flow (openrag_chat)

RAG-enhanced conversation using the knowledge base.

```mermaid
sequenceDiagram
    participant AIApp as AI Application
    participant MCP as MCP Server
    participant SDK as OpenRAG SDK
    participant API as OpenRAG API
    participant KB as Knowledge Base

    AIApp->>MCP: JSON-RPC: tools/call<br/>name: openrag_chat<br/>args: {message, chat_id?, filter_id?, limit?, score_threshold?}
    activate MCP

    MCP->>MCP: Validate message not empty
    MCP->>SDK: client.chat.create(...)
    activate SDK

    SDK->>API: POST /api/chat<br/>X-API-Key: orag_xxx
    activate API

    Note over API,KB: RAG Pipeline

    API->>KB: Semantic search for relevant chunks
    activate KB
    KB-->>API: Matching document chunks with scores
    deactivate KB

    API->>API: Build context from chunks
    API->>API: Generate LLM response with context
    API-->>SDK: {response, sources[], chat_id}
    deactivate API

    SDK-->>MCP: ChatResponse object
    deactivate SDK

    MCP->>MCP: Format response with sources
    MCP-->>AIApp: TextContent with answer + sources + chat_id
    deactivate MCP

    Note over AIApp,MCP: Conversation Continuation

    AIApp->>MCP: JSON-RPC: tools/call<br/>name: openrag_chat<br/>args: {message, chat_id: "prev_id"}
    MCP->>SDK: client.chat.create(chat_id=prev_id)
    SDK->>API: POST /api/chat (with chat_id)
    API->>API: Load conversation history
    API->>KB: Search with conversation context
    KB-->>API: Relevant chunks
    API-->>SDK: Contextual response
    SDK-->>MCP: ChatResponse
    MCP-->>AIApp: Continued conversation response
```

---

## 3. Search Flow (openrag_search)

Semantic search over the knowledge base.

```mermaid
sequenceDiagram
    participant AIApp as AI Application
    participant MCP as MCP Server
    participant SDK as OpenRAG SDK
    participant API as OpenRAG API
    participant KB as Knowledge Base

    AIApp->>MCP: JSON-RPC: tools/call<br/>name: openrag_search<br/>args: {query, limit?, score_threshold?, filter_id?, data_sources?, document_types?}
    activate MCP

    MCP->>MCP: Validate query not empty
    MCP->>MCP: Build SearchFilters if data_sources or document_types provided
    MCP->>SDK: client.search.query(...)
    activate SDK

    SDK->>API: POST /api/search<br/>X-API-Key: orag_xxx
    activate API

    API->>API: Generate query embedding
    API->>KB: k-NN vector search with filters
    activate KB
    KB-->>API: Scored document chunks
    deactivate KB

    API->>API: Apply score_threshold filter
    API-->>SDK: {results[{filename, text, score, page}]}
    deactivate API

    SDK-->>MCP: SearchResponse object
    deactivate SDK

    alt Results found
        MCP->>MCP: Format results with scores<br/>Truncate content > 500 chars
        MCP-->>AIApp: TextContent with formatted results
    else No results
        MCP-->>AIApp: "No results found."
    end
    deactivate MCP
```

---

## 4. File Ingestion Flow (openrag_ingest_file)

Ingest local files into the knowledge base with sync or async modes.

```mermaid
sequenceDiagram
    participant AIApp as AI Application
    participant MCP as MCP Server
    participant SDK as OpenRAG SDK
    participant API as OpenRAG API
    participant KB as Knowledge Base

    Note over AIApp,KB: Synchronous Ingestion (wait=true, default)

    AIApp->>MCP: JSON-RPC: tools/call<br/>name: openrag_ingest_file<br/>args: {file_path, wait: true}
    activate MCP

    MCP->>MCP: Validate file exists and is a file
    MCP->>SDK: client.documents.ingest(file_path, wait=true)
    activate SDK

    SDK->>API: POST /api/documents/upload<br/>multipart/form-data
    activate API

    API->>API: Parse document (Docling)
    API->>API: Chunk document
    API->>API: Generate embeddings
    API->>KB: Index chunks with vectors
    activate KB
    KB-->>API: Indexing complete
    deactivate KB

    API-->>SDK: {status: "completed", successful_files, failed_files}
    deactivate API

    SDK-->>MCP: IngestResponse
    deactivate SDK

    MCP-->>AIApp: "Successfully ingested 'filename'"
    deactivate MCP

    Note over AIApp,KB: Asynchronous Ingestion (wait=false)

    AIApp->>MCP: JSON-RPC: tools/call<br/>name: openrag_ingest_file<br/>args: {file_path, wait: false}
    activate MCP

    MCP->>MCP: Validate file exists
    MCP->>SDK: client.documents.ingest(file_path, wait=false)
    activate SDK

    SDK->>API: POST /api/documents/upload
    activate API
    API-->>SDK: {task_id: "abc123", filename}
    deactivate API

    SDK-->>MCP: IngestResponse with task_id
    deactivate SDK

    MCP-->>AIApp: "Queued for ingestion. Task ID: abc123"
    deactivate MCP

    Note over API,KB: Background Processing
    API--)KB: Async: Parse, chunk, embed, index
```

---

## 5. URL Ingestion Flow (openrag_ingest_url)

Ingest content from web URLs.

```mermaid
sequenceDiagram
    participant AIApp as AI Application
    participant MCP as MCP Server
    participant SDK as OpenRAG SDK
    participant API as OpenRAG API
    participant KB as Knowledge Base

    AIApp->>MCP: JSON-RPC: tools/call<br/>name: openrag_ingest_url<br/>args: {url}
    activate MCP

    MCP->>MCP: Validate URL starts with http:// or https://
    MCP->>SDK: client.chat.create(message with URL)
    activate SDK

    SDK->>API: POST /api/chat<br/>X-API-Key: orag_xxx
    activate API

    Note over API: Agent processes URL ingestion request

    API->>API: Fetch URL content
    API->>API: Parse HTML/content
    API->>API: Chunk and embed
    API->>KB: Index content
    activate KB
    KB-->>API: Indexed
    deactivate KB

    API-->>SDK: {response: "URL ingested successfully"}
    deactivate API

    SDK-->>MCP: ChatResponse
    deactivate SDK

    MCP-->>AIApp: "URL ingestion requested. [response]"
    deactivate MCP
```

---

## 6. Task Status Flow (openrag_get_task_status)

Check the status of an async ingestion task.

```mermaid
sequenceDiagram
    participant AIApp as AI Application
    participant MCP as MCP Server
    participant SDK as OpenRAG SDK
    participant API as OpenRAG API

    AIApp->>MCP: JSON-RPC: tools/call<br/>name: openrag_get_task_status<br/>args: {task_id}
    activate MCP

    MCP->>MCP: Validate task_id not empty
    MCP->>SDK: client.documents.get_task_status(task_id)
    activate SDK

    SDK->>API: GET /api/documents/tasks/{task_id}<br/>X-API-Key: orag_xxx
    activate API

    API-->>SDK: {status, task_id, total_files, processed_files, successful_files, failed_files, files}
    deactivate API

    SDK-->>MCP: TaskStatus object
    deactivate SDK

    MCP->>MCP: Format status report
    MCP-->>AIApp: TextContent with task status details
    deactivate MCP
```

---

## 7. Wait for Task Flow (openrag_wait_for_task)

Poll until an ingestion task completes.

```mermaid
sequenceDiagram
    participant AIApp as AI Application
    participant MCP as MCP Server
    participant SDK as OpenRAG SDK
    participant API as OpenRAG API

    AIApp->>MCP: JSON-RPC: tools/call<br/>name: openrag_wait_for_task<br/>args: {task_id, timeout?}
    activate MCP

    MCP->>MCP: Validate task_id not empty
    MCP->>SDK: client.documents.wait_for_task(task_id, timeout)
    activate SDK

    loop Poll until complete or timeout
        SDK->>API: GET /api/documents/tasks/{task_id}
        activate API
        API-->>SDK: {status: "processing", ...}
        deactivate API
        SDK->>SDK: Sleep interval
    end

    SDK->>API: GET /api/documents/tasks/{task_id}
    activate API
    API-->>SDK: {status: "completed", ...}
    deactivate API

    SDK-->>MCP: TaskStatus (final)
    deactivate SDK

    alt Task completed
        MCP-->>AIApp: "Task Completed: [status details]"
    else Timeout
        MCP-->>AIApp: "Task did not complete within X seconds"
    end
    deactivate MCP
```

---

## 8. Delete Document Flow (openrag_delete_document)

Remove a document from the knowledge base.

```mermaid
sequenceDiagram
    participant AIApp as AI Application
    participant MCP as MCP Server
    participant SDK as OpenRAG SDK
    participant API as OpenRAG API
    participant KB as Knowledge Base

    AIApp->>MCP: JSON-RPC: tools/call<br/>name: openrag_delete_document<br/>args: {filename}
    activate MCP

    MCP->>MCP: Validate filename not empty
    MCP->>SDK: client.documents.delete(filename)
    activate SDK

    SDK->>API: DELETE /api/documents/{filename}<br/>X-API-Key: orag_xxx
    activate API

    API->>KB: Delete all chunks for filename
    activate KB
    KB-->>API: Deleted chunk count
    deactivate KB

    API-->>SDK: {success: true, deleted_chunks: N}
    deactivate API

    SDK-->>MCP: DeleteResponse
    deactivate SDK

    alt Success
        MCP-->>AIApp: "Successfully deleted 'filename' (N chunks removed)"
    else Not found
        MCP-->>AIApp: "Document not found: [message]"
    end
    deactivate MCP
```

---

## 9. Error Handling

All tools implement consistent error handling.

```mermaid
sequenceDiagram
    participant AIApp as AI Application
    participant MCP as MCP Server
    participant SDK as OpenRAG SDK
    participant API as OpenRAG API

    AIApp->>MCP: JSON-RPC: tools/call
    activate MCP
    MCP->>SDK: API call
    activate SDK
    SDK->>API: HTTPS request
    activate API

    alt AuthenticationError (401)
        API-->>SDK: 401 Unauthorized
        SDK-->>MCP: AuthenticationError
        MCP-->>AIApp: "Authentication error: [message]"
    else ValidationError (400)
        API-->>SDK: 400 Bad Request
        SDK-->>MCP: ValidationError
        MCP-->>AIApp: "Invalid request: [message]"
    else RateLimitError (429)
        API-->>SDK: 429 Too Many Requests
        SDK-->>MCP: RateLimitError
        MCP-->>AIApp: "Rate limited: [message]"
    else ServerError (5xx)
        API-->>SDK: 500 Internal Server Error
        SDK-->>MCP: ServerError
        MCP-->>AIApp: "Server error: [message]"
    else NotFoundError (404)
        API-->>SDK: 404 Not Found
        SDK-->>MCP: NotFoundError
        MCP-->>AIApp: "Not found: [message]"
    else Success
        API-->>SDK: 200 OK with data
        SDK-->>MCP: Response object
        MCP-->>AIApp: Formatted success response
    end

    deactivate API
    deactivate SDK
    deactivate MCP
```

---

## Complete Architecture Overview

```mermaid
sequenceDiagram
    participant User as User/AI Agent
    participant AIApp as AI Application
    participant MCP as MCP Server
    participant SDK as OpenRAG SDK
    participant API as OpenRAG API
    participant KB as Knowledge Base

    Note over User,KB: End-to-End Knowledge Workflow

    User->>AIApp: "Ingest this PDF"
    AIApp->>MCP: openrag_ingest_file
    MCP->>SDK: documents.ingest()
    SDK->>API: POST /api/documents/upload
    API->>KB: Index embeddings
    KB-->>API: Done
    API-->>SDK: Success
    SDK-->>MCP: IngestResponse
    MCP-->>AIApp: "Ingested successfully"
    AIApp-->>User: Document added

    User->>AIApp: "What does it say about X?"
    AIApp->>MCP: openrag_chat
    MCP->>SDK: chat.create()
    SDK->>API: POST /api/chat
    API->>KB: Semantic search
    KB-->>API: Relevant chunks
    API->>API: LLM generates response
    API-->>SDK: Response + sources
    SDK-->>MCP: ChatResponse
    MCP-->>AIApp: Answer with citations
    AIApp-->>User: RAG-enhanced answer

    User->>AIApp: "Find all references to Y"
    AIApp->>MCP: openrag_search
    MCP->>SDK: search.query()
    SDK->>API: POST /api/search
    API->>KB: Vector search
    KB-->>API: Scored results
    API-->>SDK: SearchResponse
    SDK-->>MCP: Results
    MCP-->>AIApp: Formatted results
    AIApp-->>User: Search results with scores
```

---

## Protocol Details

| Layer | Protocol | Format |
|:------|:---------|:-------|
| AI App ↔ MCP Server | stdio | JSON-RPC 2.0 |
| MCP Server ↔ OpenRAG API | HTTPS | REST + JSON |
| Authentication | Header | `X-API-Key: orag_xxx` |

## Tool Summary

| Tool | Purpose | Key Parameters |
|:-----|:--------|:---------------|
| `openrag_chat` | RAG conversation | message, chat_id, filter_id, limit, score_threshold |
| `openrag_search` | Semantic search | query, limit, score_threshold, filter_id, data_sources, document_types |
| `openrag_ingest_file` | Ingest local file | file_path, wait |
| `openrag_ingest_url` | Ingest from URL | url |
| `openrag_get_task_status` | Check task status | task_id |
| `openrag_wait_for_task` | Wait for completion | task_id, timeout |
| `openrag_delete_document` | Remove document | filename |
