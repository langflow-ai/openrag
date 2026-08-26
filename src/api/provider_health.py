"""Provider health check endpoint."""

import asyncio

import httpx
from fastapi import Depends
from fastapi.responses import JSONResponse

from api.provider_validation import sanitize_provider_error_content, validate_provider_setup
from config.settings import get_openrag_config
from dependencies import require_permission
from services import provider_error_log
from services.model_catalog import is_known_provider
from session_manager import User
from utils import provider_health_cache
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def check_provider_health(
    provider: str | None = None,
    test_completion: bool = False,
    model: str | None = None,
    embedding_model_override: str | None = None,
    user: User = Depends(require_permission("providers:read")),
):
    """
    Check if the configured provider is healthy and properly validated.

    Query parameters:
        provider (optional): Provider to check ('openai', 'ollama', 'watsonx', 'anthropic').
                           If not provided, checks the currently configured provider.
        test_completion (optional): If true, performs full validation with completion/embedding tests.
        model (optional): Validate against this chat model instead of the configured one.
                          Generic LiteLLM providers are validated by issuing a real call, which
                          needs a model name; a provider that is not the selected LLM/embedding
                          provider has none, and one whose model names are deployment-specific
                          (Azure, Bedrock, SageMaker) cannot be validated against the catalogue's
                          generic names. Only meaningful together with ``provider``.
        embedding_model_override (optional): Same, for validating an embedding model instead.

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
        if not is_known_provider(provider):
            return JSONResponse(
                {
                    "status": "error",
                    "message": f"Unknown LiteLLM provider: {provider}",
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
                # "endpoint" doubles as the validation target's base URL;
                # openai's provider config exposes that as "base_url" instead.
                endpoint = getattr(provider_config, "endpoint", None) or getattr(
                    provider_config, "base_url", None
                )
                project_id = getattr(provider_config, "project_id", None)
                credentials = current_config.providers.credential_values(provider)

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

                # An explicit model wins over whatever the provider happens to be
                # selected for. Setting one clears the other so the validator
                # tests exactly what the caller asked for rather than falling
                # back to an embedding call for a chat model (or vice versa).
                if model or embedding_model_override:
                    llm_model = model or None
                    embedding_model = embedding_model_override or None
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
            # "endpoint" doubles as the validation target's base URL; openai's
            # provider config exposes that as "base_url" instead.
            endpoint = getattr(llm_provider_config, "endpoint", None) or getattr(
                llm_provider_config, "base_url", None
            )
            project_id = getattr(llm_provider_config, "project_id", None)
            llm_model = current_config.agent.llm_model

            embedding_api_key = getattr(embedding_provider_config, "api_key", None)
            embedding_endpoint = getattr(embedding_provider_config, "endpoint", None) or getattr(
                embedding_provider_config, "base_url", None
            )
            embedding_project_id = getattr(embedding_provider_config, "project_id", None)
            embedding_model = current_config.knowledge.embedding_model
            credentials = current_config.providers.credential_values(provider)
            embedding_credentials = current_config.providers.credential_values(embedding_provider)

            # Short-circuit identical concurrent polls from the provider-health
            # banner so we don't fan out N watsonx round-trips per poll cycle.
            # Only the polled (no `check_provider`) success path is cached; the
            # 503 branch and the specific-provider branch always re-validate.
            health_cache_key = provider_health_cache.cache_key(
                provider=provider,
                embedding_provider=embedding_provider,
                test_completion=test_completion,
                credentials=credentials,
                llm_model=llm_model,
                embedding_model=embedding_model,
                endpoint=endpoint,
                project_id=project_id,
                api_key=api_key,
                embedding_api_key=embedding_api_key,
                embedding_endpoint=embedding_endpoint,
                embedding_project_id=embedding_project_id,
                embedding_credentials=embedding_credentials,
            )
            # A cached *healthy* verdict must not outlive a real failure. The
            # cache exists to coalesce identical probes, and a recorded failure
            # means traffic is failing right now regardless of what the last
            # probe concluded — so fall through and let the response below
            # report it.
            has_real_failure = bool(
                provider_error_log.latest_failure(provider, "chat")
                or provider_error_log.latest_failure(embedding_provider, "embedding")
            )
            cached_payload = provider_health_cache.get(health_cache_key)
            if cached_payload is not None and not has_real_failure:
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
                if cached_payload is not None and not has_real_failure:
                    logger.debug("Returning cached provider-health response (waited for in-flight)")
                    return JSONResponse(cached_payload, status_code=200)
                # Leader's validation failed; retry leader election rather than
                # all waiters fanning out to validate simultaneously.

        logger.info(f"Checking health for provider: {provider}")

        # Validate provider setup
        if check_provider:
            # Validate specific provider
            # Generic LiteLLM providers keep their secrets in ``credentials``
            # rather than the dedicated api_key/endpoint/project_id fields, so
            # this must be forwarded or validating one from the providers page
            # runs with no credentials at all.
            await validate_provider_setup(
                provider=provider,
                api_key=api_key,
                embedding_model=embedding_model,
                llm_model=llm_model,
                endpoint=endpoint,
                project_id=project_id,
                test_completion=test_completion,
                credentials=credentials,
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
                    credentials=credentials,
                )
            except httpx.TimeoutException as e:
                # Timeout means provider is busy, not misconfigured
                if provider == "ollama":
                    llm_error = None  # Don't treat as error
                    logger.info(f"LLM provider ({provider}) appears busy: {str(e)}")
                else:
                    llm_error = sanitize_provider_error_content(e)
                    logger.error(f"LLM provider ({provider}) validation timed out: {llm_error}")
            except Exception as e:
                llm_error = sanitize_provider_error_content(e)
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
                    credentials=embedding_credentials,
                )
            except httpx.TimeoutException as e:
                # Timeout means provider is busy, not misconfigured
                if embedding_provider == "ollama":
                    embedding_error = None  # Don't treat as error
                    logger.info(f"Embedding provider ({embedding_provider}) appears busy: {str(e)}")
                else:
                    embedding_error = sanitize_provider_error_content(e)
                    logger.error(
                        f"Embedding provider ({embedding_provider}) validation timed out: {embedding_error}"
                    )
            except Exception as e:
                embedding_error = sanitize_provider_error_content(e)
                logger.error(
                    f"Embedding provider ({embedding_provider}) validation failed: {embedding_error}"
                )

            # A real call beats a probe. The probe sends its own request, so it
            # hits its own failure: OpenAI checks request shape before billing,
            # which is how a probe can report "no credits remaining" while the
            # agent's own call reports a 400 about its parameters. Both are
            # true; the actionable one is the one the user's traffic produced.
            # An entry only exists while calls are still failing — the gateway
            # erases it on the next success.
            llm_error = provider_error_log.latest_failure(provider, "chat") or llm_error
            embedding_error = (
                provider_error_log.latest_failure(embedding_provider, "embedding")
                or embedding_error
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
        error_message = sanitize_provider_error_content(e)
        logger.error(f"Provider health check failed for {provider}: {error_message}")

        return JSONResponse(
            {
                "status": "unhealthy",
                "message": error_message,
                "provider": provider,
            },
            status_code=503,
        )
