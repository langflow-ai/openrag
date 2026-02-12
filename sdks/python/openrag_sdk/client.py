"""OpenRAG SDK client."""

import os
from typing import Any

import httpx

from .chat import ChatClient
from .documents import DocumentsClient
from .exceptions import (
    AuthenticationError,
    NotFoundError,
    OpenRAGError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from .knowledge_filters import KnowledgeFiltersClient
from .search import SearchClient


class ModelsClient:
    """Client for listing available models per provider."""

    def __init__(self, client: "OpenRAGClient"):
        self._client = client

    async def list(self, provider: str):
        """
        List available language and embedding models for a provider.

        Args:
            provider: One of openai, anthropic, ollama, watsonx.

        Returns:
            ModelsResponse with language_models and embedding_models lists.
        """
        from .models import ModelsResponse

        response = await self._client._request(
            "GET", f"/api/v1/models/{provider}"
        )
        data = response.json()
        return ModelsResponse(**data)


class SettingsClient:
    """Client for settings operations."""

    def __init__(self, client: "OpenRAGClient"):
        self._client = client

    async def get(self):
        """
        Get current OpenRAG configuration.

        Returns:
            SettingsResponse with agent and knowledge settings.
        """
        from .models import SettingsResponse

        response = await self._client._request("GET", "/api/v1/settings")
        data = response.json()
        return SettingsResponse(**data)

    async def update(self, options):
        """
        Update OpenRAG configuration.

        Args:
            options: SettingsUpdateOptions or dict with settings to update.

        Returns:
            SettingsUpdateResponse with success message.
        """
        from .models import SettingsUpdateOptions, SettingsUpdateResponse

        if isinstance(options, SettingsUpdateOptions):
            body = options.model_dump(exclude_none=True)
        else:
            body = {k: v for k, v in options.items() if v is not None}

        response = await self._client._request("POST", "/api/v1/settings", json=body)
        data = response.json()
        return SettingsUpdateResponse(message=data.get("message", "Settings updated"))


class OpenRAGClient:
    """
    OpenRAG API client.

    The client can be configured via constructor arguments or environment variables:
    - OPENRAG_API_KEY: API key for authentication
    - OPENRAG_URL: Base URL for the OpenRAG frontend (default: http://localhost:3000)

    Usage:
        # Using environment variables
        async with OpenRAGClient() as client:
            response = await client.chat.create(message="Hello")

        # Using explicit arguments
        async with OpenRAGClient(api_key="orag_...", base_url="https://api.example.com") as client:
            response = await client.chat.create(message="Hello")

        # Without context manager
        client = OpenRAGClient()
        try:
            response = await client.chat.create(message="Hello")
        finally:
            await client.close()
    """

    DEFAULT_BASE_URL = "http://localhost:3000"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ):
        """
        Initialize the OpenRAG client.

        Args:
            api_key: API key for authentication. Falls back to OPENRAG_API_KEY env var.
            base_url: Base URL for the API. Falls back to OPENRAG_URL env var, then default.
            timeout: Request timeout in seconds (default 30).
            http_client: Optional custom httpx.AsyncClient instance.
        """
        # Resolve API key from argument or environment
        self._api_key = api_key or os.environ.get("OPENRAG_API_KEY")
        if not self._api_key:
            raise AuthenticationError(
                "API key is required. Set OPENRAG_API_KEY environment variable or pass api_key argument."
            )

        # Resolve base URL from argument or environment
        self._base_url = (
            base_url
            or os.environ.get("OPENRAG_URL")
            or self.DEFAULT_BASE_URL
        ).rstrip("/")

        self._timeout = timeout
        self._owns_http_client = http_client is None

        # Create or use provided HTTP client
        if http_client:
            self._http = http_client
        else:
            self._http = httpx.AsyncClient(timeout=timeout)

        # Initialize sub-clients
        self.chat = ChatClient(self)
        self.search = SearchClient(self)
        self.documents = DocumentsClient(self)
        self.settings = SettingsClient(self)
        self.models = ModelsClient(self)
        self.knowledge_filters = KnowledgeFiltersClient(self)

    @property
    def _headers(self) -> dict[str, str]:
        """Get request headers with authentication."""
        return {
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        files: dict[str, tuple[str, Any]] | None = None,
        **kwargs,
    ) -> httpx.Response:
        """Make an authenticated request to the API."""
        url = f"{self._base_url}{path}"
        headers = self._headers.copy()

        # Handle file uploads
        if files:
            del headers["Content-Type"]  # Let httpx set multipart content type
            response = await self._http.request(
                method,
                url,
                headers=headers,
                files=files,
                **kwargs,
            )
        else:
            response = await self._http.request(
                method,
                url,
                headers=headers,
                json=json,
                **kwargs,
            )

        self._handle_error(response)
        return response

    def _handle_error(self, response: httpx.Response) -> None:
        """Handle error responses."""
        if response.status_code < 400:
            return

        try:
            data = response.json()
            message = data.get("error", response.text)
        except Exception:
            message = response.text or f"HTTP {response.status_code}"

        status_code = response.status_code

        if status_code == 401:
            raise AuthenticationError(message, status_code)
        elif status_code == 403:
            raise AuthenticationError(message, status_code)
        elif status_code == 404:
            raise NotFoundError(message, status_code)
        elif status_code == 400:
            raise ValidationError(message, status_code)
        elif status_code == 429:
            raise RateLimitError(message, status_code)
        elif status_code >= 500:
            raise ServerError(message, status_code)
        else:
            raise OpenRAGError(message, status_code)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._owns_http_client:
            await self._http.aclose()

    async def __aenter__(self) -> "OpenRAGClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
