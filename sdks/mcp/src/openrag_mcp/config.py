"""Configuration for OpenRAG MCP server."""

import os

from openrag_sdk import OpenRAGClient


def _parse_float(key: str, default: float) -> float:
    """Parse a positive float from environment."""
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        value = float(raw)
        return value if value > 0 else default
    except ValueError:
        return default


def _parse_int(key: str, default: int) -> int:
    """Parse a positive int from environment."""
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        value = int(raw)
        return value if value > 0 else default
    except ValueError:
        return default


def _parse_bool(key: str, default: bool) -> bool:
    """Parse a boolean from environment (true/false, 1/0)."""
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes")


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

        # MCP httpx client configuration (OPENRAG_MCP_*)
        self.mcp_timeout = _parse_float("OPENRAG_MCP_TIMEOUT", 60.0)
        self.mcp_max_connections = _parse_int("OPENRAG_MCP_MAX_CONNECTIONS", 100)
        self.mcp_max_keepalive_connections = _parse_int(
            "OPENRAG_MCP_MAX_KEEPALIVE_CONNECTIONS", 20
        )
        self.mcp_max_retries = _parse_int("OPENRAG_MCP_MAX_RETRIES", 3)
        self.mcp_follow_redirects = _parse_bool("OPENRAG_MCP_FOLLOW_REDIRECTS", True)

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
        timeout=config.mcp_timeout,
        limits=httpx.Limits(
            max_connections=config.mcp_max_connections,
            max_keepalive_connections=config.mcp_max_keepalive_connections,
        ),
        transport=httpx.AsyncHTTPTransport(retries=config.mcp_max_retries),
        follow_redirects=config.mcp_follow_redirects,
    )
