"""Utility functions for building Langflow request headers."""

from typing import Dict
from utils.container_utils import transform_localhost_url


def add_provider_credentials_to_headers(headers: Dict[str, str], config) -> None:
    """Add provider credentials to headers as Langflow global variables.
    
    Args:
        headers: Dictionary of headers to add credentials to
        config: OpenRAGConfig object containing provider configurations
    """
    # Add OpenAI credentials
    if config.providers.openai.api_key:
        headers["X-LANGFLOW-GLOBAL-VAR-OPENAI_API_KEY"] = str(config.providers.openai.api_key)
    
    # Add Anthropic credentials
    if config.providers.anthropic.api_key:
        headers["X-LANGFLOW-GLOBAL-VAR-ANTHROPIC_API_KEY"] = str(config.providers.anthropic.api_key)
    
    # Add WatsonX credentials
    if config.providers.watsonx.api_key:
        headers["X-LANGFLOW-GLOBAL-VAR-WATSONX_API_KEY"] = str(config.providers.watsonx.api_key)
    
    if config.providers.watsonx.project_id:
        headers["X-LANGFLOW-GLOBAL-VAR-WATSONX_PROJECT_ID"] = str(config.providers.watsonx.project_id)
    
    # Add Ollama endpoint (with localhost transformation)
    if config.providers.ollama.endpoint:
        ollama_endpoint = transform_localhost_url(config.providers.ollama.endpoint)
        headers["X-LANGFLOW-GLOBAL-VAR-OLLAMA_BASE_URL"] = str(ollama_endpoint)


def build_mcp_global_vars_from_config(config) -> Dict[str, str]:
    """Build MCP global variables dictionary from OpenRAG configuration.
    
    Args:
        config: OpenRAGConfig object containing provider configurations
        
    Returns:
        Dictionary of global variables for MCP servers (without X-Langflow-Global-Var prefix)
    """
    global_vars = {}
    
    # Add OpenAI credentials
    if config.providers.openai.api_key:
        global_vars["OPENAI_API_KEY"] = config.providers.openai.api_key
    
    # Add Anthropic credentials
    if config.providers.anthropic.api_key:
        global_vars["ANTHROPIC_API_KEY"] = config.providers.anthropic.api_key
    
    # Add WatsonX credentials
    if config.providers.watsonx.api_key:
        global_vars["WATSONX_API_KEY"] = config.providers.watsonx.api_key
    
    if config.providers.watsonx.project_id:
        global_vars["WATSONX_PROJECT_ID"] = config.providers.watsonx.project_id
    
    # Add Ollama endpoint (with localhost transformation)
    if config.providers.ollama.endpoint:
        ollama_endpoint = transform_localhost_url(config.providers.ollama.endpoint)
        global_vars["OLLAMA_BASE_URL"] = ollama_endpoint
    
    # Add selected embedding model
    if config.knowledge.embedding_model:
        global_vars["SELECTED_EMBEDDING_MODEL"] = config.knowledge.embedding_model
    
    return global_vars

