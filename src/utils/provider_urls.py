"""URL helpers for OpenAI-compatible provider endpoints."""

from urllib.parse import urlsplit


def openai_compatible_url(api_base: str | None, path: str) -> str:
    """Join an OpenAI API path to a configured base URL.

    OpenAI-compatible gateways often use a path prefix of their own, so keep
    the configured path intact instead of replacing it with ``/v1``.
    """
    base = (api_base or "https://api.openai.com/v1").strip().rstrip("/")
    try:
        parsed = urlsplit(base)
        _port = parsed.port  # Validate the port syntax and range.
    except ValueError as exc:
        raise ValueError("OpenAI-compatible API base must be a valid HTTPS URL") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or "?" in base
        or "#" in base
    ):
        raise ValueError(
            "OpenAI-compatible API base must be an HTTPS URL without embedded credentials, "
            "a query, or a fragment"
        )
    return f"{base}/{path.lstrip('/')}"
