"""OpenRAG SDK data models."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# Chat models
class Source(BaseModel):
    """A source document returned in chat/search results."""

    filename: str
    text: str
    score: float
    page: int | None = None
    mimetype: str | None = None


class ChatResponse(BaseModel):
    """Response from a non-streaming chat request."""

    response: str
    chat_id: str | None = None
    sources: list[Source] = Field(default_factory=list)


class StreamEvent(BaseModel):
    """Base class for streaming events."""

    type: Literal["content", "sources", "done"]


class ContentEvent(StreamEvent):
    """A content delta event during streaming."""

    type: Literal["content"] = "content"
    delta: str


class SourcesEvent(StreamEvent):
    """A sources event containing retrieved documents."""

    type: Literal["sources"] = "sources"
    sources: list[Source]


class DoneEvent(StreamEvent):
    """Indicates the stream is complete."""

    type: Literal["done"] = "done"
    chat_id: str | None = None


# Search models
class SearchResult(BaseModel):
    """A single search result."""

    filename: str
    text: str
    score: float
    page: int | None = None
    mimetype: str | None = None


class SearchResponse(BaseModel):
    """Response from a search request."""

    results: list[SearchResult]


# Document models
class IngestResponse(BaseModel):
    """Response from document ingestion (async task-based)."""

    task_id: str
    status: str | None = None  # Optional - we poll for actual status
    filename: str | None = None


class IngestTaskStatus(BaseModel):
    """Status of an ingestion task."""

    task_id: str
    status: str  # "pending", "running", "completed", "failed"
    total_files: int = 0
    processed_files: int = 0
    successful_files: int = 0
    failed_files: int = 0
    files: dict = {}  # Detailed per-file status


class DeleteDocumentResponse(BaseModel):
    """Response from document deletion."""

    success: bool
    deleted_chunks: int = 0


# Chat history models
class Message(BaseModel):
    """A message in a conversation."""

    role: str
    content: str
    timestamp: str | None = None


class Conversation(BaseModel):
    """A conversation summary."""

    chat_id: str
    title: str = ""
    created_at: str | None = None
    last_activity: str | None = None
    message_count: int = 0


class ConversationDetail(Conversation):
    """A conversation with full message history."""

    messages: list[Message] = Field(default_factory=list)


class ConversationListResponse(BaseModel):
    """Response from listing conversations."""

    conversations: list[Conversation]


# Settings models
class AgentSettings(BaseModel):
    """Agent configuration settings."""

    llm_provider: str | None = None
    llm_model: str | None = None


class KnowledgeSettings(BaseModel):
    """Knowledge base configuration settings."""

    embedding_provider: str | None = None
    embedding_model: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None


class SettingsResponse(BaseModel):
    """Response from settings endpoint."""

    agent: AgentSettings = Field(default_factory=AgentSettings)
    knowledge: KnowledgeSettings = Field(default_factory=KnowledgeSettings)


# Request models
class SearchFilters(BaseModel):
    """Filters for search requests."""

    data_sources: list[str] | None = None
    document_types: list[str] | None = None
