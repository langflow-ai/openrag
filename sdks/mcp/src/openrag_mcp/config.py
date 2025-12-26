"""Configuration for OpenRAG MCP server."""

import os

from openrag_sdk import OpenRAGClient


class Config:
    """Configuration loaded from environment variables."""

    def __init__(self):
        self.openrag_url = os.environ.get("OPENRAG_URL", "http://localhost:3000")
        self.api_key = os.environ.get("OPENRAG_API_KEY")

        if not self.api_key:
            raise ValueError(
                "OPENRAG_API_KEY environment variable is required. "
                "Create an API key in OpenRAG Settings > API Keys."
            )

    @property
    def headers(self) -> dict[str, str]:
        """Get HTTP headers for API requests."""
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }


_config: Config | None = None
_openrag_client: OpenRAGClient | None = None


def get_config() -> Config:
    """Get singleton config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def get_openrag_client() -> OpenRAGClient:
    """Get singleton OpenRAGClient instance."""
    global _openrag_client
    if _openrag_client is None:
        # OpenRAGClient reads OPENRAG_API_KEY and OPENRAG_URL from env
        _openrag_client = OpenRAGClient()
    return _openrag_client


def get_client():
    """Get an httpx async client configured for OpenRAG.
    
    This is kept for backward compatibility with operations
    not yet supported by the SDK (list_documents, ingest_url).
    """
    import httpx

    config = get_config()
    return httpx.AsyncClient(
        base_url=config.openrag_url,
        headers=config.headers,
        timeout=60.0,
    )
