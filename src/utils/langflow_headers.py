"""Utility functions for building Langflow request headers."""

from typing import Dict
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
    if provider_lower == "azure_ai_foundry":
        return "Azure AI Foundry"
    return provider


def build_ibm_opensearch_vars(
    credentials: str,
    prefix: str = "X-LANGFLOW-GLOBAL-VAR-",
) -> Dict[str, str]:
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
    headers: Dict[str, str],
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
        headers["X-LANGFLOW-GLOBAL-VAR-WATSONX_PROJECT_ID"] = str(config.providers.watsonx.project_id)

    # Add Ollama endpoint (with localhost transformation)
    if config.providers.ollama.endpoint:
        if flows_service:
            ollama_endpoint = await flows_service.resolve_ollama_url(config.providers.ollama.endpoint)
        else:
            ollama_endpoint = transform_localhost_url(config.providers.ollama.endpoint)
        headers["X-LANGFLOW-GLOBAL-VAR-OLLAMA_BASE_URL"] = str(ollama_endpoint)

    # Inject OpenSearch URL so Langflow flows always use the correct endpoint
    from config.settings import LANGFLOW_OPENSEARCH_HOST, LANGFLOW_OPENSEARCH_PORT
    headers["X-LANGFLOW-GLOBAL-VAR-OPENSEARCH_URL"] = f"https://{LANGFLOW_OPENSEARCH_HOST}:{LANGFLOW_OPENSEARCH_PORT}"

    # IBM mode: inject OpenSearch Basic credentials as separate global vars
    from config.settings import IBM_AUTH_ENABLED
    if IBM_AUTH_ENABLED and jwt_token:
        headers.update(build_ibm_opensearch_vars(jwt_token, prefix="X-LANGFLOW-GLOBAL-VAR-"))


def build_model_provider_headers(config, embedding_model: str = None) -> Dict[str, str]:
    """Build Langflow global-variable headers for the selected models/providers.

    The flows bind EmbeddingModel.provider and the vector store's
    embedding_model_provider to SELECTED_EMBEDDING_MODEL_PROVIDER with
    load_from_db, so the provider has to reach Langflow as a global. It must be
    the display name Langflow's unified model components expect ("Azure AI
    Foundry"), not the raw config value ("azure_ai_foundry") — hence
    map_provider.
    """
    knowledge = getattr(config, "knowledge", None)
    agent = getattr(config, "agent", None)
    emb_model = embedding_model or getattr(knowledge, "embedding_model", None)
    emb_provider = getattr(knowledge, "embedding_provider", None)
    llm_model = getattr(agent, "llm_model", None)
    llm_provider = getattr(agent, "llm_provider", None)

    return {
        "X-LANGFLOW-GLOBAL-VAR-SELECTED_EMBEDDING_MODEL": str(emb_model or ""),
        "X-LANGFLOW-GLOBAL-VAR-SELECTED_EMBEDDING_MODEL_PROVIDER": map_provider(emb_provider),
        "X-LANGFLOW-GLOBAL-VAR-SELECTED_LANGUAGE_MODEL": str(llm_model or ""),
        "X-LANGFLOW-GLOBAL-VAR-SELECTED_LANGUAGE_MODEL_PROVIDER": map_provider(llm_provider),
    }



