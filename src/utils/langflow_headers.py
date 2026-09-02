"""Utility functions for building Langflow request headers."""

from urllib.parse import quote


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
    user_id: str | None = None,
) -> None:
    """Add Langflow global variables for the OpenRAG LLM proxy and infra URLs.

    Provider API keys are NOT forwarded. Langflow's Language/Embedding Model
    components (and the OpenRAG LLM/Embeddings custom components)
    speak OpenAI-compatible HTTP to OpenRAG (`OPENRAG_LLM_BASE_URL`) and
    authenticate with a short-lived hop token as `OPENRAG_LLM_TOKEN` — same
    pattern as `OPENRAG_INGEST_TOKEN`, scoped to the LLM proxy only.
    Chat and embeddings share that base URL and hop token.

    NOTE: `headers` may hold a JWT after this call. Never log it directly —
    use utils.logging_config.sanitize_headers() if a header dict must be logged.
    """
    from config.settings import get_langflow_llm_base_url
    from services.langflow_llm_token_service import LangflowLlmTokenService

    headers["X-LANGFLOW-GLOBAL-VAR-OPENRAG_LLM_BASE_URL"] = get_langflow_llm_base_url()

    subject = (user_id or "").strip() or "anonymous"
    hop_token = LangflowLlmTokenService().create_token(user_id=subject)
    headers["X-LANGFLOW-GLOBAL-VAR-OPENRAG_LLM_TOKEN"] = hop_token
    # Stock Language/Embedding Model nodes still bind api_key to OPENAI_API_KEY.
    headers["X-LANGFLOW-GLOBAL-VAR-OPENAI_API_KEY"] = hop_token

    # Inject OpenSearch and Docling URLs and index name so Langflow flows always use the correct endpoints
    from config.settings import (
        IBM_AUTH_ENABLED,
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

    if IBM_AUTH_ENABLED and jwt_token:
        headers.update(build_ibm_opensearch_vars(jwt_token, prefix="X-LANGFLOW-GLOBAL-VAR-"))


def build_model_provider_headers(config, embedding_model: str | None = None) -> dict[str, str]:
    """Build Langflow global variable headers for selected models.

    Provider is always OpenAI so Langflow uses its OpenAI-compatible client
    against the OpenRAG LLM proxy. The real provider lives in OpenRAG config
    and is applied by the gateway when it routes the model name.
    """
    emb_model = embedding_model or getattr(
        getattr(config, "knowledge", None), "embedding_model", None
    )
    agent = getattr(config, "agent", None)
    llm_model = getattr(agent, "llm_model", None)

    return {
        "X-LANGFLOW-GLOBAL-VAR-SELECTED_EMBEDDING_MODEL": str(emb_model or ""),
        "X-LANGFLOW-GLOBAL-VAR-SELECTED_EMBEDDING_MODEL_PROVIDER": "OpenAI",
        "X-LANGFLOW-GLOBAL-VAR-SELECTED_LANGUAGE_MODEL": str(llm_model or ""),
        "X-LANGFLOW-GLOBAL-VAR-SELECTED_LANGUAGE_MODEL_PROVIDER": "OpenAI",
    }
