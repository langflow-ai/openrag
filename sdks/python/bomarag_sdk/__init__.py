"""
BomaRAG Python SDK.

A Python client library for the BomaRAG API.

Usage:
    from bomarag_sdk import BomaRAGClient

    # Using environment variables (BOMARAG_API_KEY, BOMARAG_URL)
    async with BomaRAGClient() as client:
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

from .client import BomaRAGClient
from .exceptions import (
    AuthenticationError,
    BomaRAGError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from .knowledge_filters import KnowledgeFiltersClient
from .models import (
    AgentSettings,
    ChatResponse,
    ContentEvent,
    Conversation,
    ConversationDetail,
    ConversationListResponse,
    CreateKnowledgeFilterOptions,
    CreateKnowledgeFilterResponse,
    DeleteDocumentResponse,
    DeleteKnowledgeFilterResponse,
    DoneEvent,
    FileRecord,
    GetAllFilesResponse,
    GetKnowledgeFilterResponse,
    IngestResponse,
    KnowledgeFilter,
    KnowledgeFilterQueryData,
    KnowledgeFilterSearchResponse,
    KnowledgeSettings,
    ListFilesResponse,
    Message,
    PrincipalLabel,
    SearchFilters,
    SearchResponse,
    SearchResult,
    SettingsResponse,
    SettingsUpdateOptions,
    SettingsUpdateResponse,
    Source,
    SourcesEvent,
    StreamEvent,
    UpdateKnowledgeFilterOptions,
)

__version__ = "0.4.0"

__all__ = [
    # Main client
    "BomaRAGClient",
    # Sub-clients
    "KnowledgeFiltersClient",
    # Exceptions
    "BomaRAGError",
    "AuthenticationError",
    "RateLimitError",
    "NotFoundError",
    "ValidationError",
    "ServerError",
    # File models
    "FileRecord",
    "GetAllFilesResponse",
    "ListFilesResponse",
    "PrincipalLabel",
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
    "SettingsUpdateOptions",
    "SettingsUpdateResponse",
    "AgentSettings",
    "KnowledgeSettings",
    # Knowledge filter models
    "KnowledgeFilter",
    "KnowledgeFilterQueryData",
    "CreateKnowledgeFilterOptions",
    "UpdateKnowledgeFilterOptions",
    "CreateKnowledgeFilterResponse",
    "KnowledgeFilterSearchResponse",
    "GetKnowledgeFilterResponse",
    "DeleteKnowledgeFilterResponse",
]
