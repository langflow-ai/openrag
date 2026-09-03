"""Provider validation utilities for testing API keys and models during onboarding."""

import asyncio
import json
import re
from typing import Any

import httpx

from utils.container_utils import transform_localhost_url
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Peel leading "Error <label>:" wrappers (e.g. Langflow graph/component noise).
# Requires a label after "Error" so bare "Error: …" messages are preserved.
_ERROR_LABEL_PREFIX_RE = re.compile(r"^Error\s+\S[^:]*:\s*", re.IGNORECASE)


def _strip_error_label_prefixes(text: str) -> str:
    """Remove leading ``Error <label>:`` segments; keep the innermost message."""
    cleaned = text.strip()
    while True:
        updated = _ERROR_LABEL_PREFIX_RE.sub("", cleaned, count=1).strip()
        if updated == cleaned:
            return cleaned
        cleaned = updated


_PROVIDER_CREDENTIAL_ERROR_MARKERS = (
    "incorrect api key",
    "invalid api key",
    "invalid_api_key",
    "api key could not be found",
    "api key is invalid",
    "api key has been revoked",
    "api key revoked",
    "revoked api key",
    "provided api key could not be found",
    # IBM IAM returns this when the key still exists but is toggled off.
    "api key is disabled",
    "api key disabled",
    "authentication_error",
    "failed to authenticate",
    "invalid x-api-key",
    "unauthorized",
    "authentication failed",
    "invalid credentials",
    "could not authenticate",
)


_PROVIDER_ERROR_CONTENT_MARKERS = _PROVIDER_CREDENTIAL_ERROR_MARKERS + (
    "rate limit",
    "rate_limit",
    "permission denied",
    "quota exceeded",
    "provider request failed",
    "insufficient_quota",
)


def _extract_balanced_json_object(text: str) -> str | None:
    """Return the first top-level `{...}` substring, ignoring trailing junk."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _humanize_provider_error_message(message: str) -> str:
    """Rewrite provider-specific messages into clearer user-facing copy."""
    lowered = message.lower()
    # IBM IAM returns "could not be found" for invalid/unknown keys.
    if "api key could not be found" in lowered:
        return "Provided API key is Invalid."
    return message


def format_provider_error_message(exc: BaseException | str) -> str:
    """Return a concise, user-facing provider error string from an exception or text."""
    text = _strip_error_label_prefixes((str(exc) if not isinstance(exc, str) else exc).strip())
    if not text:
        return "An error occurred while generating a response."

    parsed = _parse_json_error_message(text)
    if parsed != text:
        # Pure JSON (or JSON-shaped) payloads: prefer the extracted message only.
        return _humanize_provider_error_message(_strip_error_label_prefixes(parsed))

    json_blob = _extract_balanced_json_object(text)
    if json_blob:
        nested = _parse_json_error_message(json_blob)
        if nested != json_blob:
            # Embedded provider JSON already has the real message — drop wrappers.
            return _humanize_provider_error_message(_strip_error_label_prefixes(nested))

    return _humanize_provider_error_message(text)


def is_provider_credential_error(text: str | BaseException | None) -> bool:
    """True when the error indicates an invalid, missing, or revoked provider API key."""
    if text is None:
        return False
    lowered = (str(text) if not isinstance(text, str) else text).lower()
    return any(marker in lowered for marker in _PROVIDER_CREDENTIAL_ERROR_MARKERS)


_GENERIC_UPSTREAM_ERROR_MARKERS = (
    "an unknown error occurred",
    "an error occurred while generating a response",
    "unknown error occurred",
    "something went wrong",
)


def is_generic_upstream_error(text: str | BaseException | None) -> bool:
    """True when upstream returned an opaque error with no actionable detail."""
    if text is None:
        return True
    lowered = (str(text) if not isinstance(text, str) else text).strip().lower().rstrip(".")
    if not lowered:
        return True
    generics = {marker.rstrip(".") for marker in _GENERIC_UPSTREAM_ERROR_MARKERS}
    return lowered in generics


def looks_like_provider_error_content(text: str | None) -> bool:
    """True when assistant text looks like a provider/auth failure rather than a normal reply."""
    if not text or not text.strip():
        return False
    content = text.strip()
    if content.startswith("Error:"):
        return True
    if is_generic_upstream_error(content):
        return True
    lowered = content.lower()
    if any(marker in lowered for marker in _PROVIDER_ERROR_CONTENT_MARKERS):
        return True
    # Raw provider payloads often embed JSON error objects.
    if "{" in content and (
        '"error"' in lowered
        or '"errormessage"' in lowered
        or '"errorcode"' in lowered
        or '"errors"' in lowered
    ):
        return True
    return False


def sanitize_provider_error_content(text: str | BaseException | None) -> str:
    """Format provider error text and fall back when JSON still leaks through."""
    if text is None:
        return "An error occurred while generating a response."
    if not isinstance(text, str):
        text = str(text)
    if not text.strip():
        return "An error occurred while generating a response."
    cleaned = format_provider_error_message(text)
    if "{" in cleaned or "}" in cleaned:
        if is_provider_credential_error(text) or is_provider_credential_error(cleaned):
            return (
                "The configured API key is invalid or has been revoked. "
                "Update it in Settings and retry."
            )
        # Strip the first JSON object as a last resort.
        json_start = cleaned.find("{")
        prefix = cleaned[:json_start].rstrip(": ").strip()
        return prefix or "An error occurred while generating a response."
    return cleaned


_LANGFLOW_TRANSPORT_ERROR_MARKERS = (
    "server disconnected",
    "disconnected without sending a response",
    "remote protocol error",
    "connection reset",
    "broken pipe",
    "all connection attempts failed",
    "connection refused",
)


def is_langflow_transport_error(text: str | BaseException | None) -> bool:
    """True when Langflow dropped the HTTP connection mid-ingest."""
    if text is None:
        return False
    lowered = (str(text) if not isinstance(text, str) else text).lower()
    return any(marker in lowered for marker in _LANGFLOW_TRANSPORT_ERROR_MARKERS)


async def _probe_provider_credential_error(
    *,
    provider: str | None,
    api_key: str | None,
    endpoint: str | None = None,
    project_id: str | None = None,
    embedding_model: str | None = None,
    llm_model: str | None = None,
    credentials: dict[str, str] | None = None,
) -> str | None:
    """Run a lightweight provider check; return a cleaned credential error if auth fails."""
    if not provider:
        return None
    try:
        await validate_provider_setup(
            provider=provider,
            api_key=api_key,
            embedding_model=embedding_model,
            llm_model=llm_model,
            endpoint=endpoint,
            project_id=project_id,
            test_completion=False,
            credentials=credentials,
        )
    except Exception as probe_exc:
        cleaned = sanitize_provider_error_content(probe_exc)
        if is_provider_credential_error(probe_exc) or is_provider_credential_error(cleaned):
            return cleaned
    return None


def _provider_probe_inputs(
    config: Any,
    provider: str,
    provider_config: Any,
) -> tuple[str | None, str | None, str | None, dict[str, str]]:
    """Return legacy fields plus the complete LiteLLM credential map.

    The original four providers expose attributes such as ``api_key`` and
    ``endpoint``. Generic providers (Azure, Bedrock, Gemini, and others) keep
    every LiteLLM keyword argument in ``ProvidersConfig.credentials`` instead.
    Recovery probes must use both representations because they run specifically
    when Langflow has hidden the provider's real failure.
    """
    credentials: dict[str, str] = {}
    credential_values = getattr(getattr(config, "providers", None), "credential_values", None)
    if callable(credential_values):
        values = credential_values(provider)
        if isinstance(values, dict):
            credentials = dict(values)

    api_key = getattr(provider_config, "api_key", None) or credentials.get("api_key")
    endpoint = (
        getattr(provider_config, "resolved_endpoint", None)
        or getattr(provider_config, "endpoint", None)
        or credentials.get("api_base")
    )
    project_id = getattr(provider_config, "project_id", None) or credentials.get("project_id")
    return api_key, endpoint, project_id, credentials


async def probe_provider_credential_error() -> str | None:
    """Return a credential error if any ingest-relevant provider key fails auth.

    Langflow receives every configured provider key, so a revoked watsonx key can
    crash ingest even when the selected embedding provider is OpenAI.
    """
    from config.settings import get_openrag_config

    config = get_openrag_config()
    checked: set[str] = set()

    candidates: list[tuple[str | None, object, str | None, str | None]] = [
        (
            config.knowledge.embedding_provider,
            config.get_embedding_provider_config(),
            config.knowledge.embedding_model,
            None,
        ),
        (
            config.agent.llm_provider,
            config.get_llm_provider_config(),
            None,
            config.agent.llm_model,
        ),
    ]
    for name in ("openai", "anthropic", "watsonx", "ollama"):
        candidates.append((name, getattr(config.providers, name, None), None, None))

    for provider, provider_config, embedding_model, llm_model in candidates:
        if not provider or provider in checked or provider_config is None:
            continue
        checked.add(provider)
        api_key, endpoint, project_id, credentials = _provider_probe_inputs(
            config,
            provider,
            provider_config,
        )
        if provider == "ollama":
            if not endpoint:
                continue
        elif provider not in (
            config.knowledge.embedding_provider,
            config.agent.llm_provider,
        ) and not (api_key or credentials):
            continue

        error = await _probe_provider_credential_error(
            provider=provider,
            api_key=api_key,
            endpoint=endpoint,
            project_id=project_id,
            embedding_model=embedding_model,
            llm_model=llm_model,
            credentials=credentials,
        )
        if error:
            return error
    return None


async def probe_chat_llm_error() -> str | None:
    """Return a cleaned error if the configured chat LLM fails auth or inference.

    Unlike :func:`probe_provider_credential_error`, this runs a completion check
    against the selected ``llm_model`` so missing/deprecated models surface
    instead of being misreported as API-key failures (or left as opaque
    Langflow text).
    """
    from config.settings import get_openrag_config

    config = get_openrag_config()
    provider = config.agent.llm_provider
    llm_model = (config.agent.llm_model or "").strip()
    if not provider or not llm_model:
        return None

    provider_config = config.get_llm_provider_config()
    if provider_config is None:
        return None

    api_key, endpoint, project_id, credentials = _provider_probe_inputs(
        config,
        provider,
        provider_config,
    )
    if provider == "ollama":
        if not endpoint:
            return None
    elif not (api_key or credentials):
        return None

    try:
        # Pass only llm_model so validate_provider_setup runs completion (not
        # the embedding branch of the test_completion if/elif).
        await validate_provider_setup(
            provider=provider,
            api_key=api_key,
            llm_model=llm_model,
            endpoint=endpoint,
            project_id=project_id,
            test_completion=True,
            credentials=credentials,
        )
    except Exception as probe_exc:
        return sanitize_provider_error_content(probe_exc)
    return None


async def probe_embedding_error() -> str | None:
    """Return a cleaned error if the configured embedding model fails auth or inference."""
    from config.settings import get_openrag_config

    config = get_openrag_config()
    provider = config.knowledge.embedding_provider
    embedding_model = (config.knowledge.embedding_model or "").strip()
    if not provider or not embedding_model:
        return None

    provider_config = config.get_embedding_provider_config()
    if provider_config is None:
        return None

    api_key, endpoint, project_id, credentials = _provider_probe_inputs(
        config,
        provider,
        provider_config,
    )
    if provider == "ollama":
        if not endpoint:
            return None
    elif not (api_key or credentials):
        return None

    try:
        await validate_provider_setup(
            provider=provider,
            api_key=api_key,
            embedding_model=embedding_model,
            endpoint=endpoint,
            project_id=project_id,
            test_completion=True,
            credentials=credentials,
        )
    except Exception as probe_exc:
        return sanitize_provider_error_content(probe_exc)
    return None


async def resolve_ingest_error_message(exc: BaseException | str) -> str:
    """Sanitize ingest failures; probe model/setup when Langflow is opaque or mislabels auth.

    Langflow often reports disconnects or "API key is invalid" when the real issue is a
    missing/deprecated model. Mirror chat/banner diagnosis: test the configured embedding
    and chat LLM (``test_completion``) before falling back to lightweight credential probes.
    """
    raw = (str(exc) if not isinstance(exc, str) else exc).strip() or "Ingestion failed"
    cleaned = sanitize_provider_error_content(raw)

    should_probe = (
        is_generic_upstream_error(cleaned)
        or is_langflow_transport_error(raw)
        or is_langflow_transport_error(cleaned)
        or is_provider_credential_error(raw)
        or is_provider_credential_error(cleaned)
    )

    if should_probe:
        # Ingest primarily uses embeddings; also probe chat LLM so task UI matches the
        # banner when the selected LLM model is missing/deprecated.
        for probe_name, probe_fn in (
            ("embedding", probe_embedding_error),
            ("llm", probe_chat_llm_error),
            ("credentials", probe_provider_credential_error),
        ):
            probe = await probe_fn()
            if not probe:
                continue
            logger.info(
                "Ingest failure attributed via provider probe",
                upstream_error=cleaned,
                probe=probe_name,
                resolved_error=probe,
            )
            return probe

    if is_provider_credential_error(raw) or is_provider_credential_error(cleaned):
        return cleaned

    # Prefer the sanitized form whenever JSON / boilerplate was stripped.
    if cleaned != raw and "{" not in cleaned:
        return cleaned
    return raw


def resolve_chat_stream_error_message(text: str | BaseException | None) -> str:
    """Sanitize chat stream errors synchronously (no provider probing)."""
    raw = (str(text) if not isinstance(text, str) else text) if text is not None else ""
    if not raw.strip():
        return "An error occurred while generating a response."
    return sanitize_provider_error_content(raw)


async def resolve_chat_stream_error_message_async(
    text: str | BaseException | None,
) -> str:
    """Sanitize chat stream errors, probing the active LLM for opaque upstream text.

    Langflow often collapses auth/model failures to "An unknown error occurred."
    Probe only when the sanitized message is still generic/transport-level so we
    do not overwrite a more specific upstream failure.

    Order matters: diagnose the selected chat LLM (credentials + model) before
    scanning other configured keys. Otherwise a revoked secondary key can mask
    the real chat failure (e.g. missing watsonx model).
    """
    cleaned = resolve_chat_stream_error_message(text)
    if is_generic_upstream_error(cleaned) or is_langflow_transport_error(cleaned):
        llm_probe = await probe_chat_llm_error()
        if llm_probe:
            logger.info(
                "Chat stream opaque error attributed to configured LLM",
                upstream_error=cleaned,
                llm_error=llm_probe,
            )
            return llm_probe

        cred_probe = await probe_provider_credential_error()
        if cred_probe:
            logger.info(
                "Chat stream opaque error attributed to provider credentials",
                upstream_error=cleaned,
                credential_error=cred_probe,
            )
            return cred_probe
    return cleaned


def _parse_json_error_message(error_text: str) -> str:
    """Parse JSON error message and extract just the message field."""
    try:
        # Try to parse as JSON
        error_data = json.loads(error_text)

        if isinstance(error_data, dict):
            # WatsonX format: {"errors": [{"code": "...", "message": "..."}], ...}
            if "errors" in error_data and isinstance(error_data["errors"], list):
                errors = error_data["errors"]
                if len(errors) > 0 and isinstance(errors[0], dict):
                    message = errors[0].get("message", "")
                    if message:
                        return message
                    code = errors[0].get("code", "")
                    if code:
                        return f"Error: {code}"

            # OpenAI format: {"error": {"message": "...", "type": "...", "code": "..."}}
            if "error" in error_data:
                error_obj = error_data["error"]
                if isinstance(error_obj, dict):
                    message = error_obj.get("message", "")
                    if message:
                        return message

            # Direct message field
            if "message" in error_data:
                return error_data["message"]

            # IBM IAM format: {"errorCode": "...", "errorMessage": "...", "context": {...}}
            if "errorMessage" in error_data:
                return error_data["errorMessage"]

            # Generic format: {"detail": "..."}
            if "detail" in error_data:
                return error_data["detail"]
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # Return original text if not JSON or can't parse
    return error_text


def _extract_error_details(response: httpx.Response) -> str:
    """Extract detailed error message from API response."""
    try:
        # Try to parse JSON error response
        error_data = response.json()

        # Common error response formats
        if isinstance(error_data, dict):
            # WatsonX format: {"errors": [{"code": "...", "message": "..."}], ...}
            if "errors" in error_data and isinstance(error_data["errors"], list):
                errors = error_data["errors"]
                if len(errors) > 0 and isinstance(errors[0], dict):
                    # Extract just the message from the first error
                    message = errors[0].get("message", "")
                    if message:
                        return message
                    # Fallback to code if no message
                    code = errors[0].get("code", "")
                    if code:
                        return f"Error: {code}"

            # OpenAI format: {"error": {"message": "...", "type": "...", "code": "..."}}
            if "error" in error_data:
                error_obj = error_data["error"]
                if isinstance(error_obj, dict):
                    message = error_obj.get("message", "")
                    if message:
                        return message

            # Anthropic / generic: {"message": "..."}
            if "message" in error_data:
                return error_data["message"]

            # IBM IAM format: {"errorCode": "...", "errorMessage": "...", "context": {...}}
            if "errorMessage" in error_data:
                return error_data["errorMessage"]

            # Generic format: {"detail": "..."}
            if "detail" in error_data:
                return error_data["detail"]

        # If JSON parsing worked but no structured error found, try parsing text
        response_text = response.text[:500]
        parsed = _parse_json_error_message(response_text)
        if parsed != response_text:
            return parsed
        return response_text

    except (json.JSONDecodeError, ValueError):
        # If JSON parsing fails, try parsing the text as JSON string
        response_text = response.text[:500] if response.text else f"HTTP {response.status_code}"
        parsed = _parse_json_error_message(response_text)
        if parsed != response_text:
            return parsed
        return response_text


async def validate_provider_setup(
    provider: str,
    api_key: str = None,
    embedding_model: str = None,
    llm_model: str = None,
    endpoint: str = None,
    project_id: str = None,
    test_completion: bool = False,
    credentials: dict[str, str] | None = None,
) -> None:
    """
    Validate provider setup by testing completion with tool calling and embedding.

    Args:
        provider: Provider name ('openai', 'watsonx', 'ollama', 'anthropic', 'bedrock')
        api_key: API key for the provider (optional for ollama)
        embedding_model: Embedding model to test
        llm_model: LLM model to test
        endpoint: Provider endpoint (required for ollama and watsonx)
        project_id: Project ID (required for watsonx)
        test_completion: If True, performs full validation with completion/embedding tests (consumes credits).
                        If False, performs lightweight validation (no credits consumed). Default: False.

    Raises:
        Exception: If validation fails, raises the original exception with the actual error message.
    """
    provider_lower = provider.lower()
    supplied = dict(credentials or {})
    if api_key:
        supplied.setdefault("api_key", api_key)
    if endpoint:
        supplied.setdefault("api_base", endpoint)
    if project_id:
        supplied.setdefault("project_id", project_id)

    try:
        logger.info(
            f"Starting validation for provider: {provider_lower} (test_completion={test_completion})"
        )

        if provider_lower not in {"openai", "watsonx", "ollama", "anthropic"}:
            await _test_litellm_provider(
                provider=provider_lower,
                credentials=supplied,
                embedding_model=embedding_model,
                llm_model=llm_model,
            )
        elif test_completion:
            # Full validation with completion/embedding tests (consumes credits)
            if embedding_model:
                # Test embedding
                await test_embedding(
                    provider=provider_lower,
                    api_key=api_key,
                    embedding_model=embedding_model,
                    endpoint=endpoint,
                    project_id=project_id,
                )
            elif llm_model:
                # Test completion with tool calling
                await test_completion_with_tools(
                    provider=provider_lower,
                    api_key=api_key,
                    llm_model=llm_model,
                    endpoint=endpoint,
                    project_id=project_id,
                )
        else:
            # Lightweight validation (no credits consumed)
            await test_lightweight_health(
                provider=provider_lower,
                api_key=api_key,
                endpoint=endpoint,
                project_id=project_id,
            )

        logger.info(f"Validation successful for provider: {provider_lower}")

    except Exception as e:
        logger.error(f"Validation failed for provider {provider_lower}: {str(e)}")
        # Preserve the original error message instead of replacing it with a generic one
        raise


async def _test_litellm_provider(
    *,
    provider: str,
    credentials: dict[str, str],
    embedding_model: str | None,
    llm_model: str | None,
) -> None:
    """Validate arbitrary providers through the same LiteLLM adapter used at runtime."""
    import litellm

    model = embedding_model or llm_model
    if not model:
        raise ValueError("A model is required to validate the provider")
    litellm_model = f"{provider}/{model}"
    if embedding_model:
        await litellm.aembedding(
            model=litellm_model,
            input="OpenRAG provider validation",
            **credentials,
        )
        return
    await litellm.acompletion(
        model=litellm_model,
        messages=[{"role": "user", "content": "Reply with OK."}],
        max_tokens=4,
        **credentials,
    )


async def test_lightweight_health(
    provider: str,
    api_key: str = None,
    endpoint: str = None,
    project_id: str = None,
) -> None:
    """Test provider health with lightweight check (no credits consumed)."""

    if provider == "openai":
        await _test_openai_lightweight_health(api_key)
    elif provider == "watsonx":
        await _test_watsonx_lightweight_health(api_key, endpoint, project_id)
    elif provider == "ollama":
        await _test_ollama_lightweight_health(endpoint)
    elif provider == "anthropic":
        await _test_anthropic_lightweight_health(api_key)
    elif provider == "bedrock":
        await _test_bedrock_lightweight_health()
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def test_completion_with_tools(
    provider: str,
    api_key: str = None,
    llm_model: str = None,
    endpoint: str = None,
    project_id: str = None,
) -> None:
    """Test completion with tool calling for the provider."""

    if provider == "openai":
        await _test_openai_completion_with_tools(api_key, llm_model)
    elif provider == "watsonx":
        await _test_watsonx_completion_with_tools(api_key, llm_model, endpoint, project_id)
    elif provider == "ollama":
        await _test_ollama_completion_with_tools(llm_model, endpoint)
    elif provider == "anthropic":
        await _test_anthropic_completion_with_tools(api_key, llm_model)
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def test_embedding(
    provider: str,
    api_key: str = None,
    embedding_model: str = None,
    endpoint: str = None,
    project_id: str = None,
) -> None:
    """Test embedding generation for the provider."""

    if provider == "openai":
        await _test_openai_embedding(api_key, embedding_model)
    elif provider == "watsonx":
        await _test_watsonx_embedding(api_key, embedding_model, endpoint, project_id)
    elif provider == "ollama":
        await _test_ollama_embedding(embedding_model, endpoint)
    elif provider == "bedrock":
        # No boto3/SigV4 dependency to make a real signed embedding call from
        # here; fall back to the same credential-shape check as the
        # lightweight health check (see _test_bedrock_lightweight_health).
        await _test_bedrock_lightweight_health()
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def _http_request_with_retry(
    method: str,
    url: str,
    *,
    max_retries: int = 2,
    backoff_factor: float = 0.5,
    retryable_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504),
    retry_timeout_on_post: bool = False,
    client: httpx.AsyncClient | None = None,
    **kwargs,
) -> httpx.Response:
    """Execute an HTTP request with retries for transient network/timeout/server errors.

    Retries GET requests on network timeouts and 429/5xx status codes.
    For POST requests, retries status codes (429/5xx) by default, and only retries
    network timeouts if `retry_timeout_on_post=True` is explicitly set (e.g. for test probes).
    """
    last_exc: Exception | None = None
    is_post = method.upper() == "POST"
    for attempt in range(max_retries + 1):
        try:
            if client is not None:
                if method.upper() == "GET":
                    response = await client.get(url, **kwargs)
                elif is_post:
                    response = await client.post(url, **kwargs)
                else:
                    response = await client.request(method, url, **kwargs)
            else:
                async with httpx.AsyncClient() as ac:
                    if method.upper() == "GET":
                        response = await ac.get(url, **kwargs)
                    elif is_post:
                        response = await ac.post(url, **kwargs)
                    else:
                        response = await ac.request(method, url, **kwargs)

            if attempt < max_retries and response.status_code in retryable_status_codes:
                logger.warning(
                    "Transient HTTP %d from %s (attempt %d/%d), retrying in %.2fs...",
                    response.status_code,
                    url,
                    attempt + 1,
                    max_retries + 1,
                    backoff_factor * (2**attempt),
                )
                await asyncio.sleep(backoff_factor * (2**attempt))
                continue
            return response
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
            httpx.ConnectError,
        ) as exc:
            last_exc = exc
            if attempt < max_retries and (not is_post or retry_timeout_on_post):
                logger.warning(
                    "Transient %s requesting %s (attempt %d/%d), retrying in %.2fs...",
                    type(exc).__name__,
                    url,
                    attempt + 1,
                    max_retries + 1,
                    backoff_factor * (2**attempt),
                )
                await asyncio.sleep(backoff_factor * (2**attempt))
            else:
                raise

    if last_exc:
        raise last_exc from None
    raise RuntimeError(f"HTTP request to {url} failed after retries")


# OpenAI validation functions
async def _test_openai_lightweight_health(api_key: str) -> None:
    """Test OpenAI API key validity with lightweight check.

    Only checks if the API key is valid without consuming credits.
    Uses the /v1/models endpoint which doesn't consume credits.
    """
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Use /v1/models endpoint which validates the key without consuming credits
        response = await _http_request_with_retry(
            "GET",
            "https://api.openai.com/v1/models",
            headers=headers,
            timeout=30.0,
        )

        if response.status_code != 200:
            error_details = _extract_error_details(response)
            logger.error(
                f"OpenAI lightweight health check failed: {response.status_code} - {error_details}"
            )
            raise Exception(error_details)

        logger.info("OpenAI lightweight health check passed")

    except httpx.TimeoutException:
        logger.error("OpenAI lightweight health check timed out")
        raise Exception("OpenAI API request timed out") from None
    except Exception as e:
        logger.error(f"OpenAI lightweight health check failed: {str(e)}")
        raise


async def _test_openai_completion_with_tools(api_key: str, llm_model: str) -> None:
    """Test OpenAI completion with tool calling."""
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Simple tool calling test
        base_payload = {
            "model": llm_model,
            "messages": [{"role": "user", "content": "What tools do you have available?"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the current weather",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location": {"type": "string", "description": "The city and state"}
                            },
                            "required": ["location"],
                        },
                    },
                }
            ],
        }

        # Try with max_tokens first
        payload = {**base_payload, "max_tokens": 50}
        response = await _http_request_with_retry(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=45.0,
            retry_timeout_on_post=True,
        )

        # If max_tokens doesn't work, try with max_completion_tokens
        if response.status_code != 200:
            logger.warning(
                "[API] max_tokens parameter failed, trying max_completion_tokens instead"
            )
            payload = {**base_payload, "max_completion_tokens": 50}
            response = await _http_request_with_retry(
                "POST",
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=45.0,
                retry_timeout_on_post=True,
            )

        if response.status_code != 200:
            error_details = _extract_error_details(response)
            logger.error(f"OpenAI completion test failed: {response.status_code} - {error_details}")
            raise Exception(error_details)

        logger.info("OpenAI completion with tool calling test passed")

    except httpx.TimeoutException:
        logger.error("OpenAI completion test timed out")
        raise Exception("Request timed out") from None
    except Exception as e:
        logger.error(f"OpenAI completion test failed: {str(e)}")
        raise


async def _test_openai_embedding(api_key: str, embedding_model: str) -> None:
    """Test OpenAI embedding generation."""
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": embedding_model,
            "input": "test embedding",
        }

        response = await _http_request_with_retry(
            "POST",
            "https://api.openai.com/v1/embeddings",
            headers=headers,
            json=payload,
            timeout=45.0,
            retry_timeout_on_post=True,
        )

        if response.status_code != 200:
            error_details = _extract_error_details(response)
            logger.error(f"OpenAI embedding test failed: {response.status_code} - {error_details}")
            raise Exception(error_details)

        data = response.json()
        if not data.get("data") or len(data["data"]) == 0:
            raise Exception("No embedding data returned")

        logger.info("OpenAI embedding test passed")

    except httpx.TimeoutException:
        logger.error("OpenAI embedding test timed out")
        raise Exception("Request timed out") from None
    except Exception as e:
        logger.error(f"OpenAI embedding test failed: {str(e)}")
        raise


# IBM Watson validation functions
async def _test_watsonx_lightweight_health(api_key: str, endpoint: str, project_id: str) -> None:
    """Test WatsonX API key validity with lightweight check.

    Only checks if the API key is valid by getting a bearer token.
    Does not consume credits by avoiding model inference requests.
    """
    try:
        # Get bearer token from IBM IAM - this validates the API key without consuming credits
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://iam.cloud.ibm.com/identity/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": api_key,
                },
                timeout=10.0,  # Short timeout for lightweight check
            )

            if token_response.status_code != 200:
                error_details = _extract_error_details(token_response)
                logger.error(
                    f"IBM IAM token request failed: {token_response.status_code} - {error_details}"
                )
                raise Exception(error_details)

            bearer_token = token_response.json().get("access_token")
            if not bearer_token:
                raise Exception("No access token received from IBM")

            logger.info("WatsonX lightweight health check passed - API key is valid")

    except httpx.TimeoutException:
        logger.error("WatsonX lightweight health check timed out")
        raise Exception("WatsonX API request timed out") from None
    except Exception as e:
        logger.error(f"WatsonX lightweight health check failed: {str(e)}")
        raise


async def _test_watsonx_completion_with_tools(
    api_key: str, llm_model: str, endpoint: str, project_id: str
) -> None:
    """Test IBM Watson completion with tool calling."""
    try:
        # Get bearer token from IBM IAM
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://iam.cloud.ibm.com/identity/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": api_key,
                },
                timeout=30.0,
            )

            if token_response.status_code != 200:
                error_details = _extract_error_details(token_response)
                logger.error(
                    f"IBM IAM token request failed: {token_response.status_code} - {error_details}"
                )
                raise Exception(error_details)

            bearer_token = token_response.json().get("access_token")
            if not bearer_token:
                raise Exception("No access token received from IBM")

        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        }

        # Test completion with tools
        url = f"{endpoint}/ml/v1/text/chat"
        params = {"version": "2026-04-15"}
        payload = {
            "model_id": llm_model,
            "project_id": project_id,
            "messages": [{"role": "user", "content": "What tools do you have available?"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the current weather",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location": {"type": "string", "description": "The city and state"}
                            },
                            "required": ["location"],
                        },
                    },
                }
            ],
            "max_tokens": 50,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                params=params,
                json=payload,
                timeout=30.0,
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(
                    f"IBM Watson completion test failed: {response.status_code} - {error_details}"
                )
                # If error_details is still JSON, parse it to extract just the message
                parsed_details = _parse_json_error_message(error_details)
                raise Exception(parsed_details)

            logger.info("IBM Watson completion with tool calling test passed")

    except httpx.TimeoutException:
        logger.error("IBM Watson completion test timed out")
        raise Exception("Request timed out") from None
    except Exception as e:
        logger.error(f"IBM Watson completion test failed: {str(e)}")
        # If the error message contains JSON, parse it to extract just the message
        error_str = str(e)
        if "IBM Watson API error: " in error_str:
            json_part = error_str.split("IBM Watson API error: ", 1)[1]
            parsed_message = _parse_json_error_message(json_part)
            if parsed_message != json_part:
                raise Exception(parsed_message) from e
        raise


async def _test_watsonx_embedding(
    api_key: str, embedding_model: str, endpoint: str, project_id: str
) -> None:
    """Test IBM Watson embedding generation."""
    try:
        # Get bearer token from IBM IAM
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://iam.cloud.ibm.com/identity/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": api_key,
                },
                timeout=30.0,
            )

            if token_response.status_code != 200:
                error_details = _extract_error_details(token_response)
                logger.error(
                    f"IBM IAM token request failed: {token_response.status_code} - {error_details}"
                )
                raise Exception(error_details)

            bearer_token = token_response.json().get("access_token")
            if not bearer_token:
                raise Exception("No access token received from IBM")

        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        }

        # Test embedding
        url = f"{endpoint}/ml/v1/text/embeddings"
        params = {"version": "2026-04-15"}
        payload = {
            "model_id": embedding_model,
            "project_id": project_id,
            "inputs": ["test embedding"],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                params=params,
                json=payload,
                timeout=30.0,
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(
                    f"IBM Watson embedding test failed: {response.status_code} - {error_details}"
                )
                # If error_details is still JSON, parse it to extract just the message
                parsed_details = _parse_json_error_message(error_details)
                raise Exception(parsed_details)

            data = response.json()
            if not data.get("results") or len(data["results"]) == 0:
                raise Exception("No embedding data returned")

            logger.info("IBM Watson embedding test passed")

    except httpx.TimeoutException:
        logger.error("IBM Watson embedding test timed out")
        raise Exception("Request timed out") from None
    except Exception as e:
        logger.error(f"IBM Watson embedding test failed: {str(e)}")
        # If the error message contains JSON, parse it to extract just the message
        error_str = str(e)
        if "IBM Watson API error: " in error_str:
            json_part = error_str.split("IBM Watson API error: ", 1)[1]
            parsed_message = _parse_json_error_message(json_part)
            if parsed_message != json_part:
                raise Exception(parsed_message) from e
        raise


# Ollama validation functions
async def _test_ollama_lightweight_health(endpoint: str) -> None:
    """Test Ollama availability with lightweight status check.

    Only checks if the endpoint returns a 200 status without fetching data.
    """
    try:
        ollama_url = transform_localhost_url(endpoint)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                ollama_url,
                timeout=10.0,  # Short timeout for lightweight check
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(
                    f"Ollama lightweight health check failed: {response.status_code} - {error_details}"
                )
                raise Exception(error_details)

            logger.info("Ollama lightweight health check passed")

    except httpx.TimeoutException:
        logger.error("Ollama lightweight health check timed out")
        raise Exception("Ollama endpoint timed out") from None
    except Exception as e:
        logger.error(f"Ollama lightweight health check failed: {str(e)}")
        raise


async def _test_ollama_completion_with_tools(llm_model: str, endpoint: str) -> None:
    """Test Ollama completion with tool calling."""
    try:
        ollama_url = transform_localhost_url(endpoint)
        url = f"{ollama_url}/api/chat"

        payload = {
            "model": llm_model,
            "messages": [{"role": "user", "content": "What tools do you have available?"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the current weather",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location": {"type": "string", "description": "The city and state"}
                            },
                            "required": ["location"],
                        },
                    },
                }
            ],
            "stream": False,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                timeout=60.0,  # Increased timeout for Ollama when potentially busy
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(
                    f"Ollama completion test failed: {response.status_code} - {error_details}"
                )
                raise Exception(error_details)

            logger.info("Ollama completion with tool calling test passed")

    except httpx.TimeoutException:
        logger.error("Ollama completion test timed out")
        raise httpx.TimeoutException("Ollama is busy or model inference timed out") from None
    except Exception as e:
        logger.error(f"Ollama completion test failed: {str(e)}")
        raise


async def _test_ollama_embedding(embedding_model: str, endpoint: str) -> None:
    """Test Ollama embedding generation."""
    try:
        ollama_url = transform_localhost_url(endpoint)
        url = f"{ollama_url}/api/embeddings"

        payload = {
            "model": embedding_model,
            "prompt": "test embedding",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                timeout=60.0,  # Increased timeout for Ollama when potentially busy
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(
                    f"Ollama embedding test failed: {response.status_code} - {error_details}"
                )
                raise Exception(error_details)

            data = response.json()
            if not data.get("embedding"):
                raise Exception("No embedding data returned")

            logger.info("Ollama embedding test passed")

    except httpx.TimeoutException:
        logger.error("Ollama embedding test timed out")
        raise httpx.TimeoutException("Ollama is busy or embedding generation timed out") from None
    except Exception as e:
        logger.error(f"Ollama embedding test failed: {str(e)}")
        raise


# Anthropic validation functions
async def _test_anthropic_lightweight_health(api_key: str) -> None:
    """Test Anthropic API key validity with lightweight check.

    Only checks if the API key is valid without consuming credits.
    Uses the /v1/models endpoint which doesn't consume credits.
    """
    try:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        response = await _http_request_with_retry(
            "GET",
            "https://api.anthropic.com/v1/models",
            headers=headers,
            timeout=30.0,
        )

        if response.status_code != 200:
            error_details = _extract_error_details(response)
            logger.error(
                f"Anthropic lightweight health check failed: {response.status_code} - {error_details}"
            )
            raise Exception(error_details)

        logger.info("Anthropic lightweight health check passed")

    except httpx.TimeoutException:
        logger.error("Anthropic lightweight health check timed out")
        raise Exception("Anthropic API request timed out") from None
    except Exception as e:
        logger.error(f"Anthropic lightweight health check failed: {str(e)}")
        raise


async def _test_anthropic_completion_with_tools(api_key: str, llm_model: str) -> None:
    """Test Anthropic completion with tool calling."""
    try:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # Simple tool calling test with Anthropic's format
        payload = {
            "model": llm_model,
            "max_tokens": 50,
            "messages": [{"role": "user", "content": "What tools do you have available?"}],
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get the current weather",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string", "description": "The city and state"}
                        },
                        "required": ["location"],
                    },
                }
            ],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=30.0,
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(
                    f"Anthropic completion test failed: {response.status_code} - {error_details}"
                )
                raise Exception(error_details)

            logger.info("Anthropic completion with tool calling test passed")

    except httpx.TimeoutException:
        logger.error("Anthropic completion test timed out")
        raise Exception("Request timed out") from None
    except Exception as e:
        logger.error(f"Anthropic completion test failed: {str(e)}")
        raise


# Bedrock validation functions
async def _test_bedrock_lightweight_health() -> None:
    """Validate AWS Bedrock credential *shape* without making a live cloud call.

    Bedrock authentication is AWS SigV4 request signing (via IAM access
    keys or an IAM role/IRSA), performed by LiteLLM at call time - OpenRAG
    never signs a request directly here. A genuine "cheap" probe (e.g. a
    signed ``ListFoundationModels`` call) would require adding an AWS SDK
    dependency solely for this health check, which is out of scope since
    embedding calls themselves are routed entirely through LiteLLM.

    Instead this validates configuration shape: a region is required (with
    or without explicit keys), and if either access key field is set, both
    must be set together (a lone key or lone secret is almost always a
    misconfiguration; IAM role/IRSA setups leave both blank).

    Reads directly from config rather than accepting api_key/endpoint
    params like the other `_test_*_lightweight_health` functions, because
    BedrockConfig's field names (region/access_key_id/secret_access_key)
    don't line up with the generic api_key/endpoint slots the shared
    validation call chain (validate_provider_setup -> test_lightweight_health)
    threads through for every provider.
    """
    from config.config_manager import config_manager

    bedrock_config = config_manager.get_config().providers.bedrock
    if not bedrock_config.region:
        raise Exception("AWS Bedrock requires a region to be configured")
    if bool(bedrock_config.access_key_id) != bool(bedrock_config.secret_access_key):
        raise Exception(
            "AWS Bedrock requires both access_key_id and secret_access_key to be "
            "set together, or both left blank to use an IAM role"
        )
    logger.info("Bedrock lightweight health check passed - credential shape is valid")
