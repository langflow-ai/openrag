"""Utility functions for model name formatting and provider detection."""

from config.embedding_constants import WATSONX_EMBEDDING_DIMENSIONS
from utils.logging_config import get_logger

logger = get_logger(__name__)

KNOWN_PREFIXES = ["openai", "ollama", "watsonx", "anthropic", "gemini", "vertex_ai"]

def get_formatted_model_name(model_name: str, provider: str = "openai") -> str:
    """Format model name for LiteLLM/MCP compatibility.
    
    Ensures that non-OpenAI models have the appropriate provider prefix
    if not already present.
    
    Args:
        model_name: The name of the model (e.g., 'gpt-4o', 'nomic-embed-text:latest')
        provider: The provider name ('openai', 'ollama', 'watsonx', etc.)
        
    Returns:
        Formatted model name with prefix if needed (e.g., 'ollama/nomic-embed-text:latest')
    """
    if not model_name:
        return ""
        
    # Skip formatting if already has a known provider prefix
    if any(model_name.startswith(p + "/") for p in KNOWN_PREFIXES):
        return model_name
        
    # Detect provider from model name characteristics if prefix is missing
    if ":" in model_name:
        # Ollama models use tags with colons
        formatted_model = f"ollama/{model_name}"
        logger.debug(f"Detected Ollama model: {model_name} -> {formatted_model}")
        return formatted_model
        
    if model_name in WATSONX_EMBEDDING_DIMENSIONS:
        # WatsonX embedding models
        formatted_model = f"watsonx/{model_name}"
        logger.debug(f"Detected WatsonX model: {model_name} -> {formatted_model}")
        return formatted_model
        
    # Use explicit provider prefix if not OpenAI
    provider_lower = provider.lower() if provider else "openai"
    if provider_lower != "openai":
        formatted_model = f"{provider_lower}/{model_name}"
        logger.debug(f"Using explicit provider prefix: {model_name} -> {formatted_model}")
        return formatted_model
        
    return model_name
