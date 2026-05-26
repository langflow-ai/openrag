"""Provider health check endpoint."""

import asyncio

import httpx
from fastapi import Depends
from fastapi.responses import JSONResponse

from api.provider_validation import validate_provider_setup
from config.settings import get_openrag_config
from dependencies import get_current_user
from session_manager import User
from utils import provider_health_cache
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def check_provider_health(
    provider: str | None = None,
    test_completion: bool = False,
    user: User = Depends(get_current_user),
):
    """
    Check if the configured provider is healthy and properly validated.

    Query parameters:
        provider (optional): Provider to check ('openai', 'ollama', 'watsonx', 'anthropic').
                           If not provided, checks the currently configured provider.
        test_completion (optional): If true, performs full validation with completion/embedding tests.

    Returns:
        200: Provider is healthy and validated
        400: Invalid provider specified
        503: Provider validation failed
    """
    check_provider = provider
    _health_leader_key: str | None = None  # set when this coroutine wins leader election
    try:
        # Get current config
        current_config = get_openrag_config()

        # Determine which provider to check
        if check_provider:
            provider = check_provider.lower()
        else:
            # Default to checking LLM provider
            provider = current_config.agent.llm_provider

        # Validate provider name
        valid_providers = ["openai", "ollama", "watsonx", "anthropic"]
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
            # If checking a specific provider, use its configuration
            try:
                provider_config = current_config.providers.get_provider_config(provider)
                api_key = getattr(provider_config, "api_key", None)
                endpoint = getattr(provider_config, "endpoint", None)
                project_id = getattr(provider_config, "project_id", None)

                # Check if this provider is used for LLM or embedding
                llm_model = (
                    current_config.agent.llm_model
                    if provider == current_config.agent.llm_provider
                    else None
                )
                embedding_model = (
                    current_config.knowledge.embedding_model
                    if provider == current_config.knowledge.embedding_provider
                    else None
                )
            except ValueError:
                # Provider not found in configuration
                return JSONResponse(
                    {
                        "status": "error",
                        "message": f"Cannot validate {provider} - not currently configured. Please configure it first.",
                        "provider": provider,
                    },
                    status_code=400,
                )
        else:
            # Check both LLM and embedding providers
            embedding_provider = current_config.knowledge.embedding_provider

            llm_provider_config = current_config.get_llm_provider_config()
            embedding_provider_config = current_config.get_embedding_provider_config()

            api_key = getattr(llm_provider_config, "api_key", None)
            endpoint = getattr(llm_provider_config, "endpoint", None)
            project_id = getattr(llm_provider_config, "project_id", None)
            llm_model = current_config.agent.llm_model

            embedding_api_key = getattr(embedding_provider_config, "api_key", None)
            embedding_endpoint = getattr(embedding_provider_config, "endpoint", None)
            embedding_project_id = getattr(embedding_provider_config, "project_id", None)
            embedding_model = current_config.knowledge.embedding_model

            # Short-circuit identical concurrent polls from the provider-health
            # banner so we don't fan out N watsonx round-trips per poll cycle.
            # Only the polled (no `check_provider`) success path is cached; the
            # 503 branch and the specific-provider branch always re-validate.
            health_cache_key = provider_health_cache.cache_key(
                provider=provider,
                embedding_provider=embedding_provider,
                test_completion=test_completion,
                llm_model=llm_model,
                embedding_model=embedding_model,
                endpoint=endpoint,
                project_id=project_id,
                api_key=api_key,
                embedding_api_key=embedding_api_key,
                embedding_endpoint=embedding_endpoint,
                embedding_project_id=embedding_project_id,
            )
            cached_payload = provider_health_cache.get(health_cache_key)
            if cached_payload is not None:
                logger.debug("Returning cached provider-health response")
                return JSONResponse(cached_payload, status_code=200)

            # Singleflight: if another coroutine is already validating this
            # exact config, wait for it to finish rather than issuing a
            # redundant upstream call.
            while True:
                is_leader = await provider_health_cache.acquire(health_cache_key)
                if is_leader:
                    _health_leader_key = health_cache_key
                    break
                # Woke up after an in-flight validation completed.
                cached_payload = provider_health_cache.get(health_cache_key)
                if cached_payload is not None:
                    logger.debug("Returning cached provider-health response (waited for in-flight)")
                    return JSONResponse(cached_payload, status_code=200)
                # Leader's validation failed; retry leader election rather than
                # all waiters fanning out to validate simultaneously.

        logger.info(f"Checking health for provider: {provider}")

        # Validate provider setup
        if check_provider:
            # Validate specific provider
            await validate_provider_setup(
                provider=provider,
                api_key=api_key,
                embedding_model=embedding_model,
                llm_model=llm_model,
                endpoint=endpoint,
                project_id=project_id,
                test_completion=test_completion,
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
        else:
            # Validate both LLM and embedding providers
            # Note: For Ollama, we use lightweight checks that don't require model inference.
            # This prevents false-positive errors when Ollama is busy processing other requests.
            llm_error = None
            embedding_error = None

            # Validate LLM provider
            try:
                await validate_provider_setup(
                    provider=provider,
                    api_key=api_key,
                    llm_model=llm_model,
                    endpoint=endpoint,
                    project_id=project_id,
                    test_completion=test_completion,
                )
            except httpx.TimeoutException as e:
                # Timeout means provider is busy, not misconfigured
                if provider == "ollama":
                    llm_error = None  # Don't treat as error
                    logger.info(f"LLM provider ({provider}) appears busy: {str(e)}")
                else:
                    llm_error = str(e)
                    logger.error(f"LLM provider ({provider}) validation timed out: {llm_error}")
            except Exception as e:
                llm_error = str(e)
                logger.error(f"LLM provider ({provider}) validation failed: {llm_error}")

            # Validate embedding provider
            # For WatsonX with test_completion=True, wait 2 seconds between completion and embedding tests
            if (
                test_completion
                and provider == "watsonx"
                and embedding_provider == "watsonx"
                and llm_error is None
            ):
                logger.info(
                    "Waiting 2 seconds before WatsonX embedding test (after completion test)"
                )
                await asyncio.sleep(2)

            try:
                await validate_provider_setup(
                    provider=embedding_provider,
                    api_key=embedding_api_key,
                    embedding_model=embedding_model,
                    endpoint=embedding_endpoint,
                    project_id=embedding_project_id,
                    test_completion=test_completion,
                )
            except httpx.TimeoutException as e:
                # Timeout means provider is busy, not misconfigured
                if embedding_provider == "ollama":
                    embedding_error = None  # Don't treat as error
                    logger.info(f"Embedding provider ({embedding_provider}) appears busy: {str(e)}")
                else:
                    embedding_error = str(e)
                    logger.error(
                        f"Embedding provider ({embedding_provider}) validation timed out: {embedding_error}"
                    )
            except Exception as e:
                embedding_error = str(e)
                logger.error(
                    f"Embedding provider ({embedding_provider}) validation failed: {embedding_error}"
                )

            # Return combined status
            if llm_error or embedding_error:
                errors = []
                if llm_error:
                    errors.append(f"LLM ({provider}): {llm_error}")
                if embedding_error:
                    errors.append(f"Embedding ({embedding_provider}): {embedding_error}")

                if _health_leader_key:
                    provider_health_cache.release_error(_health_leader_key)
                    _health_leader_key = None
                return JSONResponse(
                    {
                        "status": "unhealthy",
                        "message": "; ".join(errors),
                        "llm_provider": provider,
                        "embedding_provider": embedding_provider,
                        "llm_error": llm_error,
                        "embedding_error": embedding_error,
                    },
                    status_code=503,
                )

            healthy_payload = {
                "status": "healthy",
                "message": "Both providers properly configured and validated",
                "llm_provider": provider,
                "embedding_provider": embedding_provider,
                "details": {
                    "llm_model": llm_model,
                    "embedding_model": embedding_model,
                },
            }
            provider_health_cache.set_and_release(health_cache_key, healthy_payload)
            _health_leader_key = None
            return JSONResponse(healthy_payload, status_code=200)

    except asyncio.CancelledError:
        if _health_leader_key:
            provider_health_cache.release_error(_health_leader_key)
        raise
    except Exception as e:
        if _health_leader_key:
            provider_health_cache.release_error(_health_leader_key)
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
