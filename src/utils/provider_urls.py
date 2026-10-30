"""URL helpers for OpenAI-compatible provider endpoints."""


def openai_compatible_url(api_base: str | None, path: str) -> str:
    """Join an OpenAI API path to a configured base URL.

    OpenAI-compatible gateways often use a path prefix of their own, so keep
    the configured path intact instead of replacing it with ``/v1``.
    """
    base = (api_base or "https://api.openai.com/v1").strip().rstrip("/")
    return f"{base}/{path.lstrip('/')}"
