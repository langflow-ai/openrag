"""Provider health check endpoint."""

from starlette.responses import JSONResponse
from utils.logging_config import get_logger
from config.settings import get_openrag_config
from api.provider_validation import validate_provider_setup

logger = get_logger(__name__)


async def check_provider_health(request):
    """
    Check if the configured provider is healthy and properly validated.
    
    Query parameters:
        provider (optional): Provider to check ('openai', 'ollama', 'watsonx').
                           If not provided, checks the currently configured provider.
    
    Returns:
        200: Provider is healthy and validated
        400: Invalid provider specified
        503: Provider validation failed
    """
    try:
        # Get optional provider from query params
        query_params = dict(request.query_params)
        check_provider = query_params.get("provider")
        
        # Get current config
        current_config = get_openrag_config()
        
        # Determine which provider to check
        if check_provider:
            provider = check_provider.lower()
        else:
            provider = current_config.provider.model_provider
        
        # Validate provider name
        valid_providers = ["openai", "ollama", "watsonx"]
        if provider not in valid_providers:
            return JSONResponse(
                {
                    "status": "error",
                    "message": f"Invalid provider: {provider}. Must be one of: {', '.join(valid_providers)}",
                    "provider": provider,
                },
                status_code=400,
            )
        
        # Get provider configuration
        if check_provider:
            # If checking a specific provider, we may not have all config
            # So we'll try to use what's available or fail gracefully
            if provider == current_config.provider.model_provider:
                # Use current config if checking current provider
                api_key = current_config.provider.api_key
                endpoint = current_config.provider.endpoint
                project_id = current_config.provider.project_id
                llm_model = current_config.agent.llm_model
                embedding_model = current_config.knowledge.embedding_model
            else:
                # For other providers, we can't validate without config
                return JSONResponse(
                    {
                        "status": "error",
                        "message": f"Cannot validate {provider} - not currently configured. Please configure it first.",
                        "provider": provider,
                    },
                    status_code=400,
                )
        else:
            # Check current provider
            api_key = current_config.provider.api_key
            endpoint = current_config.provider.endpoint
            project_id = current_config.provider.project_id
            llm_model = current_config.agent.llm_model
            embedding_model = current_config.knowledge.embedding_model
        
        logger.info(f"Checking health for provider: {provider}")
        
        # Validate provider setup
        await validate_provider_setup(
            provider=provider,
            api_key=api_key,
            embedding_model=embedding_model,
            llm_model=llm_model,
            endpoint=endpoint,
            project_id=project_id,
        )
        
        return JSONResponse(
            {
                "status": "healthy",
                "message": "Properly configured and validated",
                "provider": provider,
                "details": {
                    "llm_model": llm_model,
                    "embedding_model": embedding_model,
                    "endpoint": endpoint if provider in ["ollama", "watsonx"] else None,
                },
            },
            status_code=200,
        )
        
    except Exception as e:
        error_message = str(e)
        logger.error(f"Provider health check failed for {provider}: {error_message}")
        
        return JSONResponse(
            {
                "status": "unhealthy",
                "message": error_message,
                "provider": provider,
            },
            status_code=503,
        )

