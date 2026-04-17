---
name: openrag_sdk
description: Guide developers through integrating the OpenRAG SDK into applications with code examples, configuration, and best practices
---

When the user asks to integrate the OpenRAG SDK or use OpenRAG in their application, follow this workflow.

## Initial assessment phase
Before starting SDK integration:
1. Identify the OpenRAG instance:
   - Determine the base URL (e.g., `http://localhost:3000`, `https://api.example.com`)
   - Check if authentication is required (API key)
   - Test API availability: `curl <base_url>` or `curl <base_url>/health`
2. Identify the target application:
   - Programming language (Python, JavaScript/TypeScript)
   - Framework (if any): FastAPI, Flask, Express, React, Next.js, etc.
   - Project structure and existing dependencies
3. Determine integration requirements:
   - RAG chat functionality (streaming or non-streaming)
   - Semantic search
   - Document ingestion and management
   - Knowledge filters
   - Conversation history management
   - Settings management

## Primary goals
- Install the appropriate SDK package for the target language
- Configure authentication and connection settings
- Implement core functionality with working code examples
- Add proper error handling
- Test the integration locally
- Document the integration for maintainability

## SDK installation

### Python SDK
**Package:** [`openrag-sdk`](https://pypi.org/project/openrag-sdk/)

Installation:
```bash
pip install openrag-sdk
```

Or with uv:
```bash
uv add openrag-sdk
```

### TypeScript/JavaScript SDK
**Package:** [`openrag-sdk`](https://libraries.io/npm/openrag-sdk)

Installation:
```bash
npm install openrag-sdk
```

Or with other package managers:
```bash
yarn add openrag-sdk
pnpm add openrag-sdk
bun add openrag-sdk
```

### MCP Server
**Package:** [`openrag-mcp`](https://pypi.org/project/openrag-mcp/)

For MCP integration (Model Context Protocol):
```bash
pip install openrag-mcp
```

Or with uvx:
```bash
uvx openrag-mcp
```

## Configuration

### Python SDK Configuration
The SDK can be configured via environment variables or constructor arguments:

**Environment Variables:**
```bash
OPENRAG_API_KEY=your-api-key  # Required if authentication is enabled
OPENRAG_URL=http://localhost:3000  # Optional, defaults to localhost:3000
```

**Constructor Arguments:**
```python
from openrag_sdk import OpenRAGClient

# Using environment variables (auto-discovers OPENRAG_API_KEY and OPENRAG_URL)
client = OpenRAGClient()

# Using explicit arguments
client = OpenRAGClient(
    api_key="orag_...",
    base_url="https://api.example.com"
)
```

### TypeScript SDK Configuration
Similar configuration options for TypeScript:

```typescript
import { OpenRAGClient } from 'openrag-sdk';

// Using environment variables
const client = new OpenRAGClient();

// Using explicit configuration
const client = new OpenRAGClient({
  apiKey: 'orag_...',
  baseUrl: 'https://api.example.com'
});
```

## Core functionality examples

### 1. Chat (Non-streaming)

**Python:**
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
        
        # Continue conversation
        followup = await client.chat.create(
            message="Tell me more",
            chat_id=response.chat_id
        )
        print(followup.response)

asyncio.run(main())
```

**TypeScript:**
```typescript
import { OpenRAGClient } from 'openrag-sdk';

async function main() {
  const client = new OpenRAGClient();
  
  // Simple chat
  const response = await client.chat.create({
    message: "What is RAG?"
  });
  console.log(response.response);
  console.log(`Chat ID: ${response.chatId}`);
  
  // Continue conversation
  const followup = await client.chat.create({
    message: "Tell me more",
    chatId: response.chatId
  });
  console.log(followup.response);
}

main();
```

### 2. Chat (Streaming)

**Python:**
```python
async def streaming_chat():
    chat_id = None
    async with OpenRAGClient() as client:
        # Stream responses
        async for event in await client.chat.create(
            message="Explain RAG", 
            stream=True
        ):
            if event.type == "content":
                print(event.delta, end="", flush=True)
            elif event.type == "sources":
                for source in event.sources:
                    print(f"\nSource: {source.filename}")
            elif event.type == "done":
                chat_id = event.chat_id

asyncio.run(streaming_chat())
```

**Python with stream() context manager:**
```python
async def streaming_with_context():
    async with OpenRAGClient() as client:
        # Full event iteration
        async with client.chat.stream(message="Explain RAG") as stream:
            async for event in stream:
                if event.type == "content":
                    print(event.delta, end="", flush=True)
        
        # Access aggregated data after iteration
        print(f"\nChat ID: {stream.chat_id}")
        
        # Get final text directly
        async with client.chat.stream(message="Explain RAG") as stream:
            text = await stream.final_text()
            print(text)

asyncio.run(streaming_with_context())
```

**TypeScript:**
```typescript
async function streamingChat() {
  const client = new OpenRAGClient();
  
  const stream = await client.chat.create({
    message: "Explain RAG",
    stream: true
  });
  
  for await (const event of stream) {
    if (event.type === 'content') {
      process.stdout.write(event.delta);
    } else if (event.type === 'sources') {
      for (const source of event.sources) {
        console.log(`\nSource: ${source.filename}`);
      }
    } else if (event.type === 'done') {
      console.log(`\nChat ID: ${event.chatId}`);
    }
  }
}
```

### 3. Conversation History

**Python:**
```python
async def manage_conversations():
    async with OpenRAGClient() as client:
        # List all conversations
        conversations = await client.chat.list()
        for conv in conversations.conversations:
            print(f"{conv.chat_id}: {conv.title}")
        
        if not conversations.conversations:
            print("No conversations found")
            return
        
        chat_id = conversations.conversations[0].chat_id
        
        # Get specific conversation with messages
        conversation = await client.chat.get(chat_id)
        for msg in conversation.messages:
            print(f"{msg.role}: {msg.content}")
        
        # Delete conversation
        await client.chat.delete(chat_id)

asyncio.run(manage_conversations())
```

**TypeScript:**
```typescript
async function manageConversations() {
  const client = new OpenRAGClient();
  
  // List all conversations
  const conversations = await client.chat.list();
  for (const conv of conversations.conversations) {
    console.log(`${conv.chatId}: ${conv.title}`);
  }
  
  if (!conversations.conversations.length) {
    console.log("No conversations found");
    return;
  }
  
  const chatId = conversations.conversations[0].chatId;
  
  // Get specific conversation
  const conversation = await client.chat.get(chatId);
  for (const msg of conversation.messages) {
    console.log(`${msg.role}: ${msg.content}`);
  }
  
  // Delete conversation
  await client.chat.delete(chatId);
}
```

### 4. Search

**Python:**
```python
async def search_knowledge():
    async with OpenRAGClient() as client:
        # Basic search
        results = await client.search.query("document processing")
        for result in results.results:
            print(f"{result.filename} (score: {result.score})")
            print(f"{result.text[:100]}...")
        
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

asyncio.run(search_knowledge())
```

**TypeScript:**
```typescript
async function searchKnowledge() {
  const client = new OpenRAGClient();
  
  // Basic search
  const results = await client.search.query("document processing");
  
  for (const result of results.results) {
    console.log(`${result.filename} (score: ${result.score})`);
    console.log(`${result.text.substring(0, 100)}...`);
  }
  
  // Search with filters
  const filtered = await client.search.query("API documentation", {
    filters: {
      data_sources: ["api-docs.pdf"],
      document_types: ["application/pdf"]
    },
    limit: 5,
    scoreThreshold: 0.5
  });
}
```

### 5. Document Management

**Python:**
```python
async def manage_documents():
    async with OpenRAGClient() as client:
        # Ingest a file (waits for completion by default)
        result = await client.documents.ingest(file_path="./report.pdf")
        print(f"Status: {result.status}")
        
        # Ingest from file object
        with open("./report.pdf", "rb") as f:
            result = await client.documents.ingest(file=f, filename="report.pdf")
        
        # Poll for completion manually
        final_status = await client.documents.wait_for_task(result.task_id)
        print(f"Status: {final_status.status}")
        print(f"Successful files: {final_status.successful_files}")
        
        # Delete a document
        result = await client.documents.delete("report.pdf")
        print(f"Success: {result.success}")

asyncio.run(manage_documents())
```

**TypeScript:**
```typescript
async function manageDocuments() {
  const client = new OpenRAGClient();
  
  // Ingest a file
  const result = await client.documents.ingest({
    filePath: "./report.pdf"
  });
  console.log(`Status: ${result.status}`);
  
  // Poll for completion
  const finalStatus = await client.documents.waitForTask(result.task_id);
  console.log(`Status: ${finalStatus.status}`);
  console.log(`Successful files: ${finalStatus.successful_files}`);
  
  // Delete a document
  const deleteResult = await client.documents.delete("report.pdf");
  console.log(`Success: ${deleteResult.success}`);
}
```

### 6. Settings Management

**Python:**
```python
async def manage_settings():
    async with OpenRAGClient() as client:
        # Get settings
        settings = await client.settings.get()
        print(f"LLM Provider: {settings.agent.llm_provider}")
        print(f"LLM Model: {settings.agent.llm_model}")
        print(f"Embedding Model: {settings.knowledge.embedding_model}")
        
        # Update settings
        await client.settings.update({
            "llm_provider": "openai",
            "llm_model": "gpt-4o",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-small"
        })

asyncio.run(manage_settings())
```

**TypeScript:**
```typescript
async function manageSettings() {
  const client = new OpenRAGClient();
  
  // Get settings
  const settings = await client.settings.get();
  console.log(`LLM Provider: ${settings.agent.llmProvider}`);
  console.log(`LLM Model: ${settings.agent.llmModel}`);
  
  // Update settings
  await client.settings.update({
    llm_provider: "openai",
    llm_model: "gpt-4o",
    embedding_provider: "openai",
    embedding_model: "text-embedding-3-small"
  });
}
```

### 7. Knowledge Filters

**Python:**
```python
async def use_knowledge_filters():
    async with OpenRAGClient() as client:
        # Create a knowledge filter
        result = await client.knowledge_filters.create({
            "name": "Technical Docs",
            "description": "Filter for technical documentation",
            "queryData": {
                "query": "technical",
                "filters": {
                    "document_types": ["application/pdf"]
                },
                "limit": 10,
                "scoreThreshold": 0.5
            }
        })
        filter_id = result.id
        
        # Search for filters
        filters = await client.knowledge_filters.search("Technical")
        for f in filters:
            print(f"{f.name}: {f.description}")
        
        # Update a filter
        await client.knowledge_filters.update(filter_id, {
            "description": "Updated description"
        })
        
        # Delete a filter
        await client.knowledge_filters.delete(filter_id)
        
        # Use filter in chat
        response = await client.chat.create(
            message="Explain the API",
            filter_id=filter_id
        )
        
        # Use filter in search
        results = await client.search.query(
            "API endpoints",
            filter_id=filter_id
        )

asyncio.run(use_knowledge_filters())
```

**TypeScript:**
```typescript
async function useKnowledgeFilters() {
  const client = new OpenRAGClient();
  
  // Create a knowledge filter
  const result = await client.knowledgeFilters.create({
    name: "Technical Docs",
    description: "Filter for technical documentation",
    queryData: {
      query: "technical",
      filters: {
        documentTypes: ["application/pdf"]
      },
      limit: 10,
      scoreThreshold: 0.5
    }
  });
  const filterId = result.id;
  
  // Use filter in chat
  const response = await client.chat.create({
    message: "Explain the API",
    filterId: filterId
  });
  
  // Use filter in search
  const results = await client.search.query({
    query: "API endpoints",
    filterId: filterId
  });
}
```

## Error handling

### Python Error Handling
```python
from openrag_sdk import (
    OpenRAGError,
    AuthenticationError,
    NotFoundError,
    ValidationError,
    RateLimitError,
    ServerError
)

async def handle_errors():
    try:
        async with OpenRAGClient() as client:
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
        print(f"Server error: {e.message} (status: {e.status_code})")
    except OpenRAGError as e:
        print(f"API error: {e.message} (status: {e.status_code})")
```

### TypeScript Error Handling
```typescript
import {
  OpenRAGClient,
  OpenRAGError,
  AuthenticationError,
  NotFoundError,
  ValidationError,
  RateLimitError,
  ServerError
} from 'openrag-sdk';

async function handleErrors() {
  try {
    const client = new OpenRAGClient();
    const response = await client.chat.create({ message: "Hello" });
  } catch (error) {
    if (error instanceof AuthenticationError) {
      console.error(`Invalid API key: ${error.message}`);
    } else if (error instanceof NotFoundError) {
      console.error(`Resource not found: ${error.message}`);
    } else if (error instanceof ValidationError) {
      console.error(`Invalid request: ${error.message}`);
    } else if (error instanceof RateLimitError) {
      console.error(`Rate limited: ${error.message}`);
    } else if (error instanceof ServerError) {
      console.error(`Server error: ${error.message}`);
    } else if (error instanceof OpenRAGError) {
      console.error(`API error: ${error.message}`);
    }
  }
}
```

## Integration patterns

### Pattern 1: FastAPI Backend
```python
from fastapi import FastAPI, HTTPException
from openrag_sdk import OpenRAGClient
from pydantic import BaseModel

app = FastAPI()
client = OpenRAGClient()

class ChatRequest(BaseModel):
    message: str
    chat_id: str | None = None

@app.post("/api/chat")
async def chat(request: ChatRequest):
    try:
        response = await client.chat.create(
            message=request.message,
            chat_id=request.chat_id
        )
        return {
            "answer": response.response,
            "sources": [{"filename": s.filename, "score": s.score} for s in response.sources],
            "chat_id": response.chat_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/search")
async def search(query: str, limit: int = 10):
    try:
        results = await client.search.query(query, limit=limit)
        return {
            "results": [
                {
                    "filename": r.filename,
                    "text": r.text,
                    "score": r.score
                }
                for r in results.results
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Pattern 2: Express.js Backend
```typescript
import express from 'express';
import { OpenRAGClient } from 'openrag-sdk';

const app = express();
const client = new OpenRAGClient();

app.use(express.json());

app.post('/api/chat', async (req, res) => {
  try {
    const { message, chatId } = req.body;
    const response = await client.chat.create({
      message,
      chatId
    });
    
    res.json({
      answer: response.response,
      sources: response.sources.map(s => ({
        filename: s.filename,
        score: s.score
      })),
      chatId: response.chatId
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.get('/api/search', async (req, res) => {
  try {
    const { query, limit = 10 } = req.query;
    const results = await client.search.query({
      query: query as string,
      limit: Number(limit)
    });
    
    res.json({
      results: results.results.map(r => ({
        filename: r.filename,
        text: r.text,
        score: r.score
      }))
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.listen(3001, () => {
  console.log('Server running on port 3001');
});
```

### Pattern 3: React Frontend
```typescript
import { useState } from 'react';
import { OpenRAGClient } from 'openrag-sdk';

// Note: In production, proxy API calls through your backend
// to avoid exposing API keys in the browser
const client = new OpenRAGClient({
  baseUrl: process.env.REACT_APP_OPENRAG_URL
});

function ChatComponent() {
  const [message, setMessage] = useState('');
  const [chatId, setChatId] = useState<string | null>(null);
  const [response, setResponse] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    
    try {
      const result = await client.chat.create({
        message,
        chatId,
        limit: 5
      });
      
      setResponse(result.response);
      setChatId(result.chatId);
      setMessage('');
    } catch (error) {
      console.error('Chat error:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <form onSubmit={handleSubmit}>
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Ask a question..."
          disabled={loading}
        />
        <button type="submit" disabled={loading}>
          {loading ? 'Sending...' : 'Send'}
        </button>
      </form>
      {response && (
        <div className="response">
          {response}
        </div>
      )}
    </div>
  );
}
```

### Pattern 4: Streaming in React
```typescript
import { useState } from 'react';
import { OpenRAGClient } from 'openrag-sdk';

function StreamingChat() {
  const [message, setMessage] = useState('');
  const [response, setResponse] = useState('');
  const [streaming, setStreaming] = useState(false);
  const client = new OpenRAGClient();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStreaming(true);
    setResponse('');
    
    try {
      const stream = await client.chat.create({
        message,
        stream: true
      });
      
      for await (const event of stream) {
        if (event.type === 'content') {
          setResponse(prev => prev + event.delta);
        }
      }
    } catch (error) {
      console.error('Streaming error:', error);
    } finally {
      setStreaming(false);
      setMessage('');
    }
  };

  return (
    <div>
      <form onSubmit={handleSubmit}>
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          disabled={streaming}
        />
        <button type="submit" disabled={streaming}>
          {streaming ? 'Streaming...' : 'Send'}
        </button>
      </form>
      <div className="response">
        {response}
        {streaming && <span className="cursor">▊</span>}
      </div>
    </div>
  );
}
```

## Security best practices

1. **Never expose API keys in client-side code**
   - Always proxy requests through your backend
   - Use environment variables for API keys
   - Implement proper authentication in your backend

2. **Use HTTPS in production**
   - Always use HTTPS for production deployments
   - Configure proper SSL/TLS certificates

3. **Validate and sanitize inputs**
   - Validate user inputs before sending to OpenRAG
   - Sanitize outputs before displaying to users
   - Implement rate limiting on your endpoints

4. **Implement proper error handling**
   - Don't expose sensitive information in error messages
   - Log errors securely for debugging
   - Provide user-friendly error messages

5. **Follow OWASP guidelines**
   - Implement proper authentication and authorization
   - Protect against common vulnerabilities (XSS, CSRF, etc.)
   - Keep dependencies up to date

## Testing strategies

### Python Testing
```python
import pytest
from openrag_sdk import OpenRAGClient

@pytest.fixture
async def client():
    async with OpenRAGClient() as client:
        yield client

@pytest.mark.asyncio
async def test_chat_basic(client):
    response = await client.chat.create(message="Hello")
    assert response.response is not None
    assert isinstance(response.sources, list)
    assert response.chat_id is not None

@pytest.mark.asyncio
async def test_search_with_filters(client):
    results = await client.search.query(
        "test",
        filters={"document_types": ["application/pdf"]}
    )
    assert isinstance(results.results, list)
```

### TypeScript Testing
```typescript
import { describe, it, expect } from 'vitest';
import { OpenRAGClient } from 'openrag-sdk';

describe('OpenRAG SDK', () => {
  const client = new OpenRAGClient();

  it('should chat successfully', async () => {
    const response = await client.chat.create({
      message: 'Hello'
    });
    
    expect(response.response).toBeDefined();
    expect(response.sources).toBeInstanceOf(Array);
    expect(response.chatId).toBeDefined();
  });

  it('should search with filters', async () => {
    const results = await client.search.query({
      query: 'test',
      filters: {
        documentTypes: ['application/pdf']
      }
    });
    
    expect(results.results).toBeInstanceOf(Array);
  });
});
```

## Troubleshooting

### Connection Issues
- Verify the base URL is correct (e.g., `http://localhost:3000` or `https://api.example.com`)
- Test connectivity: `curl <base_url>` or `curl <base_url>/health`
- Check network connectivity if OpenRAG is on a remote server
- Ensure no firewall or network policies blocking the connection
- Verify DNS resolution if using a domain name

### Authentication Errors
- Verify API key is correct if authentication is enabled
- Check API key is properly set in environment variables
- Ensure API key has necessary permissions

### Performance Optimization
- Use appropriate `limit` values (don't retrieve more sources than needed)
- Set reasonable `score_threshold` to filter low-quality results
- Implement caching for frequently asked questions
- Use connection pooling for high-traffic applications
- Consider using streaming for better user experience

### Response Quality Issues
- Adjust `score_threshold` to filter irrelevant results
- Review and update system prompt for better responses
- Ensure knowledge base has relevant documents
- Consider using knowledge filters for domain-specific queries

## Deployment considerations

1. **Environment configuration**
   - Use different configs for dev/staging/prod
   - Store sensitive data in environment variables or secrets management
   - Use configuration files for non-sensitive settings

2. **Health checks**
   - Implement health check endpoints in your application
   - Monitor OpenRAG service availability
   - Set up alerts for failures

3. **Monitoring and logging**
   - Add logging for SDK calls
   - Track metrics (response times, error rates, etc.)
   - Use structured logging for better analysis

4. **Fallback handling**
   - Implement graceful degradation if OpenRAG is unavailable
   - Provide cached responses when possible
   - Show appropriate error messages to users

5. **Scaling**
   - Consider load balancing for high-traffic scenarios
   - Implement request queuing if needed
   - Monitor resource usage and scale accordingly

## Documentation requirements

After integration, document:
- SDK setup and configuration steps
- Available endpoints and their usage
- Example requests and responses
- Error codes and handling strategies
- Performance characteristics and limitations
- Maintenance procedures and troubleshooting

## Verification checklist

Before considering integration complete:
- [ ] SDK package installed successfully
- [ ] Client successfully connects to OpenRAG
- [ ] Chat functionality works (both streaming and non-streaming)
- [ ] Search returns relevant results
- [ ] Document ingestion works
- [ ] Settings can be retrieved and updated
- [ ] Knowledge filters can be created and used
- [ ] Error handling is implemented
- [ ] Tests are passing
- [ ] Documentation is complete
- [ ] Security best practices are followed
- [ ] Performance is acceptable for use case

## Additional resources

- **Python SDK:** https://pypi.org/project/openrag-sdk/
- **TypeScript SDK:** https://libraries.io/npm/openrag-sdk
- **MCP Server:** https://pypi.org/project/openrag-mcp/
- **GitHub Repository:** https://github.com/langflow-ai/openrag/tree/main/sdks
- **Official Documentation:** https://docs.openr.ag

## Collaboration style

- Provide working code examples based on official SDK documentation
- Test integration steps before presenting them
- Explain trade-offs between different approaches
- Surface potential issues early (performance, security, etc.)
- Keep examples focused on core functionality
- Provide both minimal and production-ready examples
- Be explicit about what requires OpenRAG to be running
- Reference official package repositories for installation