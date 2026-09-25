"""Provider health check endpoint."""

import asyncio
from typing import Any

import httpx
from fastapi import Depends
from fastapi.responses import JSONResponse

from api.provider_validation import (
    ProbeResult,
    sanitize_provider_error_content,
    validate_provider_setup,
)
from config.settings import get_openrag_config
from dependencies import require_permission
from services import provider_error_log
from services.model_catalog import is_known_provider
from session_manager import User
from utils import provider_health_cache
from utils.logging_config import get_logger

logger = get_logger(__name__)

#: `warnings[].code` for indexed vectors whose model the provider no longer serves.
STALE_EMBEDDING_SPACE = "stale_embedding_space"


#: Ceiling on re-listing a provider's models from inside a health check. The
#: listing is only an input to a diagnostic, so a slow cluster costs this at
#: most; the probes report an unreachable one in their own words.
_MODEL_REFRESH_TIMEOUT_SECONDS = 5.0


async def _refresh_live_models(provider: str) -> None:
    """Re-list what `provider` serves, if it can say, best effort.

    Only the provider being checked: the listing of any other would not be
    read, and waiting on its cluster would only slow this one's verdict. A
    provider with no enhancement, or one that cannot list its own models, has
    nothing to refresh, and is skipped without a call.

    TTL-guarded inside each enhancement, so this is a network call once every
    few minutes rather than once per poll — while the cluster answers. A failed
    listing is not cached, so an unreachable cluster is asked again on every
    poll; hence the timeout. A failure or timeout leaves the previous answer in
    place and must never fail the health check.
    """
    try:
        from enhancements.providers.registry import get as get_enhancement
        from services.model_catalog import refresh_live_models

        enhancement = get_enhancement(provider)
        if enhancement is None or not hasattr(enhancement, "fetch_models"):
            return
        await asyncio.wait_for(
            refresh_live_models(provider), timeout=_MODEL_REFRESH_TIMEOUT_SECONDS
        )
    except TimeoutError:
        logger.debug(
            "Timed out refreshing live model listing",
            provider=provider,
            timeout_seconds=_MODEL_REFRESH_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.debug("Could not refresh live model listings", provider=provider, exc_info=True)


#: Spaces per aggregation page — the same page size retrieval discovers them
#: with. A corpus has a handful: one per embedding model it was indexed with.
_EMBEDDING_SPACE_PAGE_SIZE = 100

#: Pages read before giving up. Far past any real corpus; it bounds what one
#: health poll can cost if the index is somehow full of distinct spaces.
_EMBEDDING_SPACE_MAX_PAGES = 10


async def _indexed_spaces(provider: str) -> tuple[str, ...] | None:
    """Embedding models this corpus holds vectors for, under `provider`.

    None means unknown — OpenSearch unreachable, nothing indexed, or an answer
    that may be incomplete. A partial list is never returned as if it were the
    whole: a space missing from it is a stale space that goes unreported. So
    every page of the composite aggregation is read, shard failures raise
    rather than quietly dropping buckets, and running out of pages before the
    cursor does is treated as not knowing.

    Read with the admin client, not a user-scoped one, because this is a
    property of the corpus rather than of whoever is looking; DLS would
    silently shrink it.
    """
    try:
        from config.settings import clients, get_index_name
        from utils.embedding_fields import (
            build_embedding_space_aggregation,
            embedding_space_after_keys,
            embedding_spaces_from_aggregation,
            split_embedding_space_id,
        )

        client = clients.opensearch
        if client is None:
            return None
        space_ids: list[str] = []
        after: dict[str, Any] | None = None
        for _ in range(_EMBEDDING_SPACE_MAX_PAGES):
            result = await client.search(
                index=get_index_name(),
                body={
                    "size": 0,
                    # Qualified spaces only. A legacy space records no provider,
                    # so it cannot be attributed to this one, and it is governed
                    # by OPENRAG_LEGACY_EMBEDDING_PROVIDER_MAP rather than by what
                    # the cluster serves today.
                    "aggs": build_embedding_space_aggregation(
                        size=_EMBEDDING_SPACE_PAGE_SIZE,
                        qualified_after=after,
                        include_legacy=False,
                    ),
                },
                # A failed shard must fail the read, not shrink its buckets.
                params={"allow_partial_search_results": "false"},
            )
            if result.get("timed_out"):
                logger.debug("Reading indexed embedding spaces timed out")
                return None
            space_ids.extend(space.space_id for space in embedding_spaces_from_aggregation(result))
            # Raw buckets, not parsed spaces: the parser skips blank ids, and a
            # page it thinned out is not a short one.
            buckets = (
                result.get("aggregations", {}).get("embedding_spaces", {}).get("buckets") or []
            )
            next_after, _ = embedding_space_after_keys(result)
            # A short page is the last one; a composite aggregation still hands
            # back an `after_key` for it, and following it costs an empty read.
            if len(buckets) < _EMBEDDING_SPACE_PAGE_SIZE or not next_after or next_after == after:
                break
            after = next_after
        else:
            logger.debug(
                "Indexed embedding spaces exceed the read limit",
                pages=_EMBEDDING_SPACE_MAX_PAGES,
                page_size=_EMBEDDING_SPACE_PAGE_SIZE,
            )
            return None
    except Exception:
        logger.debug("Could not read indexed embedding spaces", exc_info=True)
        return None

    key = (provider or "").strip().lower()
    models = []
    for space_id in space_ids:
        space_provider, model = split_embedding_space_id(space_id)
        if space_provider == key and model:
            models.append(model)
    return tuple(dict.fromkeys(models)) or None


async def _stale_embedding_spaces(provider: str) -> dict[str, Any] | None:
    """Indexed vector spaces whose model the provider has stopped serving.

    Nothing re-checks a corpus once it is indexed. A chunk records the space it
    was embedded in (`provider:model`), retrieval embeds the query once per
    space it finds there, and an `InferenceService` redeployed under a new
    `--served-model-name` leaves every earlier chunk pointing at a model that
    is gone. No save can be rejected over it and no probe reaches it — the
    *configured* model is fine. Retrieval skips a space it cannot embed for and
    carries on, so nothing fails outright: those documents quietly stop being
    found by meaning, and the only trace is a 502 quoting a model name that
    appears nowhere in Settings.

    A warning, never an error: the provider is serving and nothing in its setup
    is wrong. The remedy is in the corpus — re-ingest or delete — so reporting
    it as a provider failure would send the operator to the one screen that
    cannot fix it.

    Silent unless both halves are known: what the provider serves, and what the
    corpus holds. Neither absence is evidence of the other.
    """
    try:
        from enhancements.providers.registry import live_models_for

        served = live_models_for(provider, "embedding")
    except Exception:
        logger.debug("Could not read live models for %s", provider, exc_info=True)
        return None
    if not served:
        return None

    indexed = await _indexed_spaces(provider)
    if not indexed:
        return None
    stale = [model for model in indexed if model not in served]
    if not stale:
        return None
    return {
        "code": STALE_EMBEDDING_SPACE,
        "provider": provider,
        "models": stale,
        "served": list(served),
        "message": (
            f"Documents are indexed with {', '.join(repr(model) for model in stale)}, which "
            f"this endpoint no longer serves (it serves: {', '.join(served)}). Search skips "
            "those vectors, so the documents are found by keyword only until they are "
            "re-ingested or deleted."
        ),
    }


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

                # An explicit model wins over whatever the provider happens to be
                # selected for. Setting one clears the other so the validator
                # tests exactly what the caller asked for rather than falling
                # back to an embedding call for a chat model (or vice versa).
                if model or embedding_model_override:
                    llm_model = model or None
                    embedding_model = embedding_model_override or None

                # One credential set per role, because the endpoint a provider
                # is checked against depends on which kind of call it is being
                # checked for (Red Hat OpenShift AI serves the two from
                # different endpoints). Each role is probed on its own below.
                role_credentials = {
                    kind: current_config.providers.credential_values(provider, kind=kind)
                    for kind in ("chat", "embedding")
                }
                # The untranslated form as well: a provider enhancement's
                # lightweight check needs every endpoint the operator entered,
                # and each entry above has been narrowed to one of them.
                stored_credentials = current_config.providers.stored_credentials(provider)
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
            credentials = current_config.providers.credential_values(provider, kind="chat")
            embedding_credentials = current_config.providers.credential_values(
                embedding_provider, kind="embedding"
            )
            stored_credentials = current_config.providers.stored_credentials(provider)
            embedding_stored_credentials = current_config.providers.stored_credentials(
                embedding_provider
            )

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
            #
            # One probe per role the provider is selected for. The validator
            # tests a single model per call, so a provider that is both the
            # LLM and the embedding provider needs two calls, each with the
            # credentials for that role — otherwise the chat model is never
            # checked and the response below claims it was. With no model at
            # all, one lightweight check runs.
            probes = [
                (kind, model_name)
                for kind, model_name in (("chat", llm_model), ("embedding", embedding_model))
                if model_name
            ] or [("chat", None)]
            for index, (kind, model_name) in enumerate(probes):
                # Same spacing the polled branch applies between the two
                # watsonx tests, so back-to-back calls don't trip its rate limit.
                if index and test_completion and provider == "watsonx":
                    logger.info("Waiting 2 seconds before WatsonX embedding test")
                    await asyncio.sleep(2)
                await validate_provider_setup(
                    provider=provider,
                    api_key=api_key,
                    embedding_model=model_name if kind == "embedding" else None,
                    llm_model=model_name if kind == "chat" else None,
                    endpoint=endpoint,
                    project_id=project_id,
                    test_completion=test_completion,
                    credentials=role_credentials[kind],
                    stored_credentials=stored_credentials,
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
                llm_probe: ProbeResult = await validate_provider_setup(
                    provider=provider,
                    api_key=api_key,
                    llm_model=llm_model,
                    endpoint=endpoint,
                    project_id=project_id,
                    test_completion=test_completion,
                    credentials=credentials,
                    stored_credentials=stored_credentials,
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
            else:
                # Without this the banner can only be cleared by chat traffic:
                # one failed turn latches it, the frontend then polls every 5s
                # with `test_completion` while it stays latched, and a provider
                # that has recovered keeps being reported broken until the entry
                # goes stale 15 minutes later.
                #
                # But a probe cannot reproduce the request that failed (see
                # `provider_error_log`), so only one that sent the same shape
                # of request may speak for it. A passing validation can mean a
                # deployment listing (Azure), no call at all (no model set), or
                # a tool-less completion (the LiteLLM probe) — none of which
                # reaches the tool-calling failures agent traffic actually hits.
                # Clearing on those would drop the banner while chat is still
                # broken, only for the next turn to raise it again.
                if test_completion and llm_probe.model_probed and llm_probe.tools_exercised:
                    provider_error_log.record_success(provider, "chat")

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
                embedding_probe: ProbeResult = await validate_provider_setup(
                    provider=embedding_provider,
                    api_key=embedding_api_key,
                    embedding_model=embedding_model,
                    endpoint=embedding_endpoint,
                    project_id=embedding_project_id,
                    test_completion=test_completion,
                    credentials=embedding_credentials,
                    stored_credentials=embedding_stored_credentials,
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
            else:
                # An embedding request has no shape beyond model and input, so a
                # real call to the configured model is the same request traffic
                # makes. Anything short of one proves nothing about it.
                if test_completion and embedding_probe.model_probed:
                    provider_error_log.record_success(embedding_provider, "embedding")

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

            # Nothing above looks at the corpus, and a vector space outlives
            # the model that made it. Reported beside the verdict, never in it:
            # a stale space degrades search but says nothing about whether the
            # provider is serving, so it must not turn the status code.
            await _refresh_live_models(embedding_provider)
            stale_spaces = await _stale_embedding_spaces(embedding_provider)
            warnings = [stale_spaces] if stale_spaces else []

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
                        "warnings": warnings,
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
                "warnings": warnings,
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
