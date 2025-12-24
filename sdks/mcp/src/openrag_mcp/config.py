"""Configuration for OpenRAG MCP server."""

import os


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


def get_config() -> Config:
    """Get singleton config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def get_client():
    """Get an httpx async client configured for OpenRAG."""
    import httpx

    config = get_config()
    return httpx.AsyncClient(
        base_url=config.openrag_url,
        headers=config.headers,
        timeout=60.0,
    )

