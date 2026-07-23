"""Utility functions for building Langflow request headers."""

from urllib.parse import quote

from utils.container_utils import transform_localhost_url


def map_provider(provider: str | None) -> str:
    """Map provider values to the formatted names expected by Langflow.

    e.g. openai -> OpenAI, anthropic -> Anthropic, ollama -> Ollama, watsonx -> IBM WatsonX
    """
    if not provider:
        return ""
    provider_lower = provider.lower()
    if provider_lower == "openai":
        return "OpenAI"
    if provider_lower == "anthropic":
        return "Anthropic"
    if provider_lower == "ollama":
        return "Ollama"
    if provider_lower == "watsonx":
        return "IBM WatsonX"
    return provider


def ascii_safe_header_value(value) -> str:
    """Return an ASCII-only HTTP header value.

    httpx (and HTTP itself) requires header values to be ASCII-encodable, so a
    non-ASCII filename or owner name (e.g. ``こんにちは.pdf`` or ``José``) placed
    into an ``X-Langflow-Global-Var-*`` header raises ``UnicodeEncodeError``
    before the request is sent. ASCII values (including spaces) pass through
    byte-for-byte; only values containing non-ASCII characters are
    percent-encoded so they can be transmitted.

    Note: in the legacy direct-write ingestion path (no ingest-token service
    wired) the FILENAME header value is stored verbatim as the indexed
    ``filename`` column, so a non-ASCII filename lands there percent-encoded.
    The backend-router path (the default) is unaffected: it sources the
    authoritative filename from the ingest JWT context, not this header.
    """
    s = "" if value is None else str(value)
    try:
        s.encode("ascii")
        return s
    except UnicodeEncodeError:
        return quote(s, safe=" /")


def build_ibm_opensearch_vars(
    credentials: str,
    prefix: str = "X-LANGFLOW-GLOBAL-VAR-",
) -> dict[str, str]:
    """Build IBM OpenSearch auth vars from a credential string.

    Supports both ``'Basic <b64>'`` (extracts username/password + JWT) and
    ``'Bearer <token>'`` (JWT only, no username/password).

    Pass prefix="X-LANGFLOW-GLOBAL-VAR-" for HTTP headers, or prefix="" for MCP global vars.
    """
    result = {f"{prefix}JWT": credentials}
    if credentials.startswith("Basic "):
        from auth.ibm_auth import extract_ibm_credentials

        username, password = extract_ibm_credentials(credentials)
        result[f"{prefix}OPENSEARCH_USERNAME"] = username
        result[f"{prefix}OPENSEARCH_PASSWORD"] = password
    return result


async def add_provider_credentials_to_headers(
    headers: dict[str, str],
    config,
    flows_service=None,
    jwt_token: str = None,
) -> None:
    """Add provider credentials to headers as Langflow global variables.

    Args:
        headers: Dictionary of headers to add credentials to
        config: OpenRAGConfig object containing provider configurations
        flows_service: Optional FlowsService instance to resolve Ollama URLs.
        jwt_token: Optional credential string (``'Basic <b64>'`` or ``'Bearer <jwt>'``).
                   When IBM_AUTH_ENABLED, injected as Langflow global variables. Basic
                   credentials additionally provide OPENSEARCH_USERNAME and OPENSEARCH_PASSWORD.

    NOTE: `headers` ends up holding raw API keys/JWTs after this call. Never log
    it directly (e.g. logger.info(..., headers=headers) / extra_headers=...) —
    use utils.logging_config.sanitize_headers() if a header dict must be logged.
    """
    # Add OpenAI credentials
    if config.providers.openai.api_key:
        headers["X-LANGFLOW-GLOBAL-VAR-OPENAI_API_KEY"] = str(config.providers.openai.api_key)

    # Add Anthropic credentials
    if config.providers.anthropic.api_key:
        headers["X-LANGFLOW-GLOBAL-VAR-ANTHROPIC_API_KEY"] = str(config.providers.anthropic.api_key)

    # Add WatsonX credentials
    if config.providers.watsonx.api_key:
        headers["X-LANGFLOW-GLOBAL-VAR-WATSONX_APIKEY"] = str(config.providers.watsonx.api_key)

    if config.providers.watsonx.project_id:
        headers["X-LANGFLOW-GLOBAL-VAR-WATSONX_PROJECT_ID"] = str(
            config.providers.watsonx.project_id
        )

    # Add Ollama endpoint (with localhost transformation)
    if config.providers.ollama.endpoint:
        if flows_service:
            ollama_endpoint = await flows_service.resolve_ollama_url(
                config.providers.ollama.endpoint
            )
        else:
            ollama_endpoint = transform_localhost_url(config.providers.ollama.endpoint)
        headers["X-LANGFLOW-GLOBAL-VAR-OLLAMA_BASE_URL"] = str(ollama_endpoint)

    # Inject OpenSearch and Docling URLs and index name so Langflow flows always use the correct endpoints
    from config.settings import (
        get_index_name,
        get_langflow_docling_url,
        get_langflow_opensearch_url,
    )

    opensearch_url = get_langflow_opensearch_url()
    if opensearch_url:
        headers["X-LANGFLOW-GLOBAL-VAR-OPENSEARCH_URL"] = opensearch_url

    docling_url = get_langflow_docling_url()
    if docling_url:
        headers["X-LANGFLOW-GLOBAL-VAR-DOCLING_SERVE_URL"] = docling_url

    index_name = get_index_name()
    if index_name:
        headers["X-LANGFLOW-GLOBAL-VAR-OPENSEARCH_INDEX_NAME"] = index_name

    # IBM mode: inject OpenSearch Basic credentials as separate global vars
    from config.settings import IBM_AUTH_ENABLED

    if IBM_AUTH_ENABLED and jwt_token:
        headers.update(build_ibm_opensearch_vars(jwt_token, prefix="X-LANGFLOW-GLOBAL-VAR-"))


def build_model_provider_headers(config, embedding_model: str | None = None) -> dict[str, str]:
    """Build Langflow global variable headers for selected embedding and language models/providers."""
    emb_model = embedding_model or getattr(
        getattr(config, "knowledge", None), "embedding_model", None
    )
    emb_provider = getattr(getattr(config, "knowledge", None), "embedding_provider", None)
    agent = getattr(config, "agent", None)
    llm_model = getattr(agent, "llm_model", None)
    llm_provider = getattr(agent, "llm_provider", None)

    return {
        "X-LANGFLOW-GLOBAL-VAR-SELECTED_EMBEDDING_MODEL": str(emb_model or ""),
        "X-LANGFLOW-GLOBAL-VAR-SELECTED_EMBEDDING_MODEL_PROVIDER": map_provider(emb_provider),
        "X-LANGFLOW-GLOBAL-VAR-SELECTED_LANGUAGE_MODEL": str(llm_model or ""),
        "X-LANGFLOW-GLOBAL-VAR-SELECTED_LANGUAGE_MODEL_PROVIDER": map_provider(llm_provider),
    }
