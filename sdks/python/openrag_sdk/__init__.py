"""
OpenRAG Python SDK.

A Python client library for the OpenRAG API.

Usage:
    from openrag_sdk import OpenRAGClient

    # Using environment variables (OPENRAG_API_KEY, OPENRAG_URL)
    async with OpenRAGClient() as client:
        # Non-streaming chat
        response = await client.chat.create(message="What is RAG?")
        print(response.response)

        # Streaming chat with context manager
        async with client.chat.stream(message="Explain RAG") as stream:
            async for text in stream.text_stream:
                print(text, end="")

        # Search
        results = await client.search.query("document processing")

        # Ingest document
        await client.documents.ingest(file_path="./report.pdf")

        # Get settings
        settings = await client.settings.get()
"""

from .client import OpenRAGClient
from .exceptions import (
    AuthenticationError,
    NotFoundError,
    OpenRAGError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from .models import (
    AgentSettings,
    ChatResponse,
    ContentEvent,
    Conversation,
    ConversationDetail,
    ConversationListResponse,
    DeleteDocumentResponse,
    DoneEvent,
    IngestResponse,
    KnowledgeSettings,
    Message,
    SearchFilters,
    SearchResponse,
    SearchResult,
    SettingsResponse,
    Source,
    SourcesEvent,
    StreamEvent,
)

__version__ = "0.1.0"

__all__ = [
    # Main client
    "OpenRAGClient",
    # Exceptions
    "OpenRAGError",
    "AuthenticationError",
    "RateLimitError",
    "NotFoundError",
    "ValidationError",
    "ServerError",
    # Models
    "ChatResponse",
    "ContentEvent",
    "SourcesEvent",
    "DoneEvent",
    "StreamEvent",
    "Source",
    "SearchResponse",
    "SearchResult",
    "SearchFilters",
    "IngestResponse",
    "DeleteDocumentResponse",
    "Conversation",
    "ConversationDetail",
    "ConversationListResponse",
    "Message",
    "SettingsResponse",
    "AgentSettings",
    "KnowledgeSettings",
]
