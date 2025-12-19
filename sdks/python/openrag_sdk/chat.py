"""OpenRAG SDK chat client with streaming support."""

import json
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal, overload

import httpx

from .models import (
    ChatResponse,
    ContentEvent,
    Conversation,
    ConversationDetail,
    ConversationListResponse,
    DoneEvent,
    Message,
    SearchFilters,
    Source,
    SourcesEvent,
    StreamEvent,
)

if TYPE_CHECKING:
    from .client import OpenRAGClient


class ChatStream:
    """
    Context manager for streaming chat responses.

    Provides convenient access to streamed content with helpers for
    text-only streaming and final text extraction.

    Usage:
        async with client.chat.stream(message="Hello") as stream:
            async for event in stream:
                if event.type == "content":
                    print(event.delta, end="")

            # After iteration, access aggregated data
            print(f"Chat ID: {stream.chat_id}")
            print(f"Full text: {stream.text}")

        # Or use text_stream for just text deltas
        async with client.chat.stream(message="Hello") as stream:
            async for text in stream.text_stream:
                print(text, end="")

        # Or use final_text() to get the complete response
        async with client.chat.stream(message="Hello") as stream:
            text = await stream.final_text()
    """

    def __init__(
        self,
        client: "OpenRAGClient",
        message: str,
        chat_id: str | None = None,
        filters: SearchFilters | dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float = 0,
        filter_id: str | None = None,
    ):
        self._client = client
        self._message = message
        self._chat_id_input = chat_id
        self._filters = filters
        self._limit = limit
        self._score_threshold = score_threshold
        self._filter_id = filter_id

        # Aggregated data
        self._text = ""
        self._chat_id: str | None = None
        self._sources: list[Source] = []
        self._response: httpx.Response | None = None
        self._consumed = False

    @property
    def text(self) -> str:
        """The accumulated text from content events."""
        return self._text

    @property
    def chat_id(self) -> str | None:
        """The chat ID for continuing the conversation."""
        return self._chat_id

    @property
    def sources(self) -> list[Source]:
        """The sources retrieved during the conversation."""
        return self._sources

    async def __aenter__(self) -> "ChatStream":
        body: dict[str, Any] = {
            "message": self._message,
            "stream": True,
            "limit": self._limit,
            "score_threshold": self._score_threshold,
        }

        if self._chat_id_input:
            body["chat_id"] = self._chat_id_input

        if self._filters:
            if isinstance(self._filters, SearchFilters):
                body["filters"] = self._filters.model_dump(exclude_none=True)
            else:
                body["filters"] = self._filters

        if self._filter_id:
            body["filter_id"] = self._filter_id

        self._response = await self._client._http.send(
            self._client._http.build_request(
                "POST",
                f"{self._client._base_url}/api/v1/chat",
                json=body,
                headers=self._client._headers,
            ),
            stream=True,
        )

        if self._response.status_code != 200:
            await self._response.aread()
            self._client._handle_error(self._response)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._response:
            await self._response.aclose()

    def __aiter__(self) -> AsyncIterator[StreamEvent]:
        return self._iterate_events()

    async def _iterate_events(self) -> AsyncIterator[StreamEvent]:
        """Iterate over all stream events."""
        if self._consumed:
            raise RuntimeError("Stream has already been consumed")

        self._consumed = True

        if not self._response:
            raise RuntimeError("Stream not initialized")

        async for line in self._response.aiter_lines():
            line = line.strip()
            if not line:
                continue

            if line.startswith("data:"):
                data_str = line[5:].strip()
                if not data_str:
                    continue

                try:
                    data = json.loads(data_str)
                    event_type = data.get("type")

                    if event_type == "content":
                        delta = data.get("delta", "")
                        self._text += delta
                        yield ContentEvent(delta=delta)

                    elif event_type == "sources":
                        sources = [Source(**s) for s in data.get("sources", [])]
                        self._sources = sources
                        yield SourcesEvent(sources=sources)

                    elif event_type == "done":
                        self._chat_id = data.get("chat_id")
                        yield DoneEvent(chat_id=self._chat_id)

                except json.JSONDecodeError:
                    continue

    @property
    def text_stream(self) -> AsyncIterator[str]:
        """
        Iterate over just the text deltas.

        Usage:
            async for text in stream.text_stream:
                print(text, end="")
        """
        return self._iterate_text()

    async def _iterate_text(self) -> AsyncIterator[str]:
        """Iterate over text deltas only."""
        async for event in self:
            if isinstance(event, ContentEvent):
                yield event.delta

    async def final_text(self) -> str:
        """
        Consume the stream and return the complete text.

        Returns:
            The full concatenated text from all content events.
        """
        async for _ in self:
            pass
        return self._text


class ChatClient:
    """Client for chat operations with streaming support."""

    def __init__(self, client: "OpenRAGClient"):
        self._client = client

    @overload
    async def create(
        self,
        message: str,
        *,
        stream: Literal[False] = False,
        chat_id: str | None = None,
        filters: SearchFilters | dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float = 0,
        filter_id: str | None = None,
    ) -> ChatResponse: ...

    @overload
    async def create(
        self,
        message: str,
        *,
        stream: Literal[True],
        chat_id: str | None = None,
        filters: SearchFilters | dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float = 0,
        filter_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]: ...

    async def create(
        self,
        message: str,
        *,
        stream: bool = False,
        chat_id: str | None = None,
        filters: SearchFilters | dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float = 0,
        filter_id: str | None = None,
    ) -> ChatResponse | AsyncIterator[StreamEvent]:
        """
        Send a chat message.

        Args:
            message: The message to send.
            stream: Whether to stream the response (default False).
            chat_id: ID of existing conversation to continue.
            filters: Optional search filters (data_sources, document_types).
            limit: Maximum number of search results (default 10).
            score_threshold: Minimum search score threshold (default 0).
            filter_id: Optional knowledge filter ID to apply.

        Returns:
            ChatResponse if stream=False, AsyncIterator[StreamEvent] if stream=True.

        Usage:
            # Non-streaming
            response = await client.chat.create(message="Hello")
            print(response.response)

            # Streaming
            async for event in await client.chat.create(message="Hello", stream=True):
                if event.type == "content":
                    print(event.delta, end="")
        """
        if stream:
            return self._stream_response(
                message=message,
                chat_id=chat_id,
                filters=filters,
                limit=limit,
                score_threshold=score_threshold,
                filter_id=filter_id,
            )
        else:
            return await self._create_response(
                message=message,
                chat_id=chat_id,
                filters=filters,
                limit=limit,
                score_threshold=score_threshold,
                filter_id=filter_id,
            )

    async def _create_response(
        self,
        message: str,
        chat_id: str | None,
        filters: SearchFilters | dict[str, Any] | None,
        limit: int,
        score_threshold: float,
        filter_id: str | None = None,
    ) -> ChatResponse:
        """Send a non-streaming chat message."""
        body: dict[str, Any] = {
            "message": message,
            "stream": False,
            "limit": limit,
            "score_threshold": score_threshold,
        }

        if chat_id:
            body["chat_id"] = chat_id

        if filters:
            if isinstance(filters, SearchFilters):
                body["filters"] = filters.model_dump(exclude_none=True)
            else:
                body["filters"] = filters

        if filter_id:
            body["filter_id"] = filter_id

        response = await self._client._request(
            "POST",
            "/api/v1/chat",
            json=body,
        )

        data = response.json()
        sources = [Source(**s) for s in data.get("sources", [])]

        return ChatResponse(
            response=data.get("response", ""),
            chat_id=data.get("chat_id"),
            sources=sources,
        )

    async def _stream_response(
        self,
        message: str,
        chat_id: str | None,
        filters: SearchFilters | dict[str, Any] | None,
        limit: int,
        score_threshold: float,
        filter_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a chat response as an async iterator."""
        body: dict[str, Any] = {
            "message": message,
            "stream": True,
            "limit": limit,
            "score_threshold": score_threshold,
        }

        if chat_id:
            body["chat_id"] = chat_id

        if filters:
            if isinstance(filters, SearchFilters):
                body["filters"] = filters.model_dump(exclude_none=True)
            else:
                body["filters"] = filters

        if filter_id:
            body["filter_id"] = filter_id

        async with self._client._http.stream(
            "POST",
            f"{self._client._base_url}/api/v1/chat",
            json=body,
            headers=self._client._headers,
        ) as response:
            if response.status_code != 200:
                await response.aread()
                self._client._handle_error(response)

            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue

                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if not data_str:
                        continue

                    try:
                        data = json.loads(data_str)
                        event_type = data.get("type")

                        if event_type == "content":
                            yield ContentEvent(delta=data.get("delta", ""))
                        elif event_type == "sources":
                            sources = [Source(**s) for s in data.get("sources", [])]
                            yield SourcesEvent(sources=sources)
                        elif event_type == "done":
                            yield DoneEvent(chat_id=data.get("chat_id"))

                    except json.JSONDecodeError:
                        continue

    def stream(
        self,
        message: str,
        *,
        chat_id: str | None = None,
        filters: SearchFilters | dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float = 0,
        filter_id: str | None = None,
    ) -> ChatStream:
        """
        Create a streaming chat context manager.

        Args:
            message: The message to send.
            chat_id: ID of existing conversation to continue.
            filters: Optional search filters (data_sources, document_types).
            limit: Maximum number of search results (default 10).
            score_threshold: Minimum search score threshold (default 0).
            filter_id: Optional knowledge filter ID to apply.

        Returns:
            ChatStream context manager.

        Usage:
            async with client.chat.stream(message="Hello") as stream:
                async for event in stream:
                    if event.type == "content":
                        print(event.delta, end="")

                # Access after iteration
                print(f"Chat ID: {stream.chat_id}")
                print(f"Full text: {stream.text}")
        """
        return ChatStream(
            client=self._client,
            message=message,
            chat_id=chat_id,
            filters=filters,
            limit=limit,
            score_threshold=score_threshold,
            filter_id=filter_id,
        )

    async def list(self) -> ConversationListResponse:
        """
        List all conversations.

        Returns:
            ConversationListResponse with conversation metadata.
        """
        response = await self._client._request("GET", "/api/v1/chat")
        data = response.json()

        conversations = [
            Conversation(**c) for c in data.get("conversations", [])
        ]

        return ConversationListResponse(conversations=conversations)

    async def get(self, chat_id: str) -> ConversationDetail:
        """
        Get a specific conversation with full message history.

        Args:
            chat_id: The ID of the conversation to retrieve.

        Returns:
            ConversationDetail with full message history.
        """
        response = await self._client._request("GET", f"/api/v1/chat/{chat_id}")
        data = response.json()

        messages = [Message(**m) for m in data.get("messages", [])]

        return ConversationDetail(
            chat_id=data.get("chat_id", chat_id),
            title=data.get("title", ""),
            created_at=data.get("created_at"),
            last_activity=data.get("last_activity"),
            message_count=len(messages),
            messages=messages,
        )

    async def delete(self, chat_id: str) -> bool:
        """
        Delete a conversation.

        Args:
            chat_id: The ID of the conversation to delete.

        Returns:
            True if deletion was successful.
        """
        response = await self._client._request("DELETE", f"/api/v1/chat/{chat_id}")
        data = response.json()
        return data.get("success", False)


# Import Literal for type hints
from typing import Literal
