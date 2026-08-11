"""Provider validation utilities for testing API keys and models during onboarding."""

import json
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

from utils.container_utils import normalize_azure_openai_base, transform_localhost_url
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
        )
    except Exception as probe_exc:
        cleaned = sanitize_provider_error_content(probe_exc)
        if is_provider_credential_error(probe_exc) or is_provider_credential_error(cleaned):
            return cleaned
    return None


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
        api_key = getattr(provider_config, "api_key", None)
        endpoint = getattr(provider_config, "endpoint", None)
        if provider == "ollama":
            if not endpoint:
                continue
        elif (
            provider
            not in (
                config.knowledge.embedding_provider,
                config.agent.llm_provider,
            )
            and not api_key
        ):
            continue

        error = await _probe_provider_credential_error(
            provider=provider,
            api_key=api_key,
            endpoint=endpoint,
            project_id=getattr(provider_config, "project_id", None),
            embedding_model=embedding_model,
            llm_model=llm_model,
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

    api_key = getattr(provider_config, "api_key", None)
    endpoint = getattr(provider_config, "endpoint", None)
    if provider == "ollama":
        if not endpoint:
            return None
    elif not api_key:
        return None

    try:
        # Pass only llm_model so validate_provider_setup runs completion (not
        # the embedding branch of the test_completion if/elif).
        await validate_provider_setup(
            provider=provider,
            api_key=api_key,
            llm_model=llm_model,
            endpoint=endpoint,
            project_id=getattr(provider_config, "project_id", None),
            test_completion=True,
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

    api_key = getattr(provider_config, "api_key", None)
    endpoint = getattr(provider_config, "endpoint", None)
    if provider == "ollama":
        if not endpoint:
            return None
    elif not api_key:
        return None

    try:
        await validate_provider_setup(
            provider=provider,
            api_key=api_key,
            embedding_model=embedding_model,
            endpoint=endpoint,
            project_id=getattr(provider_config, "project_id", None),
            test_completion=True,
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
    api_version: str = None,
) -> None:
    """
    Validate provider setup by testing completion with tool calling and embedding.

    Args:
        provider: Provider name ('openai', 'watsonx', 'ollama', 'anthropic', 'azure_ai_foundry', 'azure_openai')
        api_key: API key for the provider (optional for ollama)
        embedding_model: Embedding model to test
        llm_model: LLM model to test
        endpoint: Provider endpoint (required for ollama and watsonx)
        project_id: Project ID (required for watsonx)
        test_completion: If True, performs full validation with completion/embedding tests (consumes credits).
                        If False, performs lightweight validation (no credits consumed). Default: False.
        api_version: API version (required for azure_openai; optional for azure_ai_foundry).

    Raises:
        Exception: If validation fails, raises the original exception with the actual error message.
    """
    provider_lower = provider.lower()

    try:
        logger.info(
            f"Starting validation for provider: {provider_lower} (test_completion={test_completion})"
        )

        if test_completion:
            # Full validation with completion/embedding tests (consumes credits)
            if embedding_model:
                # Test embedding
                await test_embedding(
                    provider=provider_lower,
                    api_key=api_key,
                    embedding_model=embedding_model,
                    endpoint=endpoint,
                    project_id=project_id,
                    api_version=api_version,
                )
            elif llm_model:
                # Test completion with tool calling
                await test_completion_with_tools(
                    provider=provider_lower,
                    api_key=api_key,
                    llm_model=llm_model,
                    endpoint=endpoint,
                    project_id=project_id,
                    api_version=api_version,
                )
        else:
            # Lightweight validation (no credits consumed)
            await test_lightweight_health(
                provider=provider_lower,
                api_key=api_key,
                endpoint=endpoint,
                project_id=project_id,
                api_version=api_version,
            )

        logger.info(f"Validation successful for provider: {provider_lower}")

    except Exception as e:
        logger.error(f"Validation failed for provider {provider_lower}: {str(e)}")
        # Preserve the original error message instead of replacing it with a generic one
        raise


async def test_lightweight_health(
    provider: str,
    api_key: str = None,
    endpoint: str = None,
    project_id: str = None,
    api_version: str = None,
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
    elif provider == "azure_ai_foundry":
        await _test_azure_ai_foundry_lightweight_health(api_key, endpoint, api_version)
    elif provider == "azure_openai":
        await _test_azure_openai_lightweight_health(api_key, endpoint, api_version)
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def test_completion_with_tools(
    provider: str,
    api_key: str = None,
    llm_model: str = None,
    endpoint: str = None,
    project_id: str = None,
    api_version: str = None,
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
    elif provider == "azure_ai_foundry":
        await _test_azure_ai_foundry_completion(api_key, llm_model, endpoint, api_version)
    elif provider == "azure_openai":
        await _test_azure_openai_completion(api_key, llm_model, endpoint, api_version)
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def test_embedding(
    provider: str,
    api_key: str = None,
    embedding_model: str = None,
    endpoint: str = None,
    project_id: str = None,
    api_version: str = None,
) -> None:
    """Test embedding generation for the provider."""

    if provider == "openai":
        await _test_openai_embedding(api_key, embedding_model)
    elif provider == "watsonx":
        await _test_watsonx_embedding(api_key, embedding_model, endpoint, project_id)
    elif provider == "ollama":
        await _test_ollama_embedding(embedding_model, endpoint)
    elif provider == "azure_ai_foundry":
        await _test_azure_ai_foundry_embedding(api_key, embedding_model, endpoint, api_version)
    elif provider == "azure_openai":
        await _test_azure_openai_embedding(api_key, embedding_model, endpoint, api_version)
    else:
        raise ValueError(f"Unknown provider: {provider}")


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

        async with httpx.AsyncClient() as client:
            # Use /v1/models endpoint which validates the key without consuming credits
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers=headers,
                timeout=10.0,  # Short timeout for lightweight check
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

        async with httpx.AsyncClient() as client:
            # Try with max_tokens first
            payload = {**base_payload, "max_tokens": 50}
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30.0,
            )

            # If max_tokens doesn't work, try with max_completion_tokens
            if response.status_code != 200:
                logger.warning(
                    "[API] max_tokens parameter failed, trying max_completion_tokens instead"
                )
                payload = {**base_payload, "max_completion_tokens": 50}
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30.0,
                )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(
                    f"OpenAI completion test failed: {response.status_code} - {error_details}"
                )
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

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers=headers,
                json=payload,
                timeout=30.0,
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(
                    f"OpenAI embedding test failed: {response.status_code} - {error_details}"
                )
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

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.anthropic.com/v1/models",
                headers=headers,
                timeout=10.0,  # Short timeout for lightweight check
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


def _merge_azure_ai_foundry_path(base_path: str, ending_path: str) -> str:
    """Append `ending_path` onto `base_path`, deduping overlapping segments.

    Mirrors LiteLLM's own `_add_path_to_api_base` exactly (litellm/utils.py),
    since the real inference call is made by LiteLLM and must resolve to the
    identical URL our own validation/listing calls hit.
    """
    base_segments = [s for s in base_path.split("/") if s]
    end_segments = [s for s in ending_path.split("/") if s]
    for i in range(len(base_segments)):
        if base_segments[i:] == end_segments[: len(base_segments) - i]:
            return "/" + "/".join(base_segments[:i] + end_segments)
    return "/" + "/".join(base_segments + end_segments)


# Azure AI Foundry's model inference API rejects requests with no
# api-version at all. Shared with langflow_sync.py, which must apply the
# same default when syncing AZURE_AI_FOUNDRY_API_VERSION to Langflow so its
# embedding/chat calls don't fail even when the user leaves the (optional)
# API Version field blank in Settings.
#
# Per Microsoft's own Azure AI Model Inference REST API reference (chat
# completions + embeddings), which uses this value in every example request:
# https://learn.microsoft.com/en-us/rest/api/aifoundry/modelinference/
#
# This default ONLY applies to that generic model-inference form
# (".../models/..."). It does NOT apply to the OpenAI-compatible
# ".../openai/v1" form some Foundry resources use instead (see
# _build_azure_ai_foundry_url) — that form is path-versioned and takes no
# dated api-version at all; Azure's own docs: "api-version is no longer a
# required parameter with the v1 GA API."
# https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle
AZURE_AI_FOUNDRY_DEFAULT_API_VERSION = "2025-04-01"

# The openai/v1 route's own api-version query param (distinct from the dated
# versions above) accepts only these literal values — never a dated string.
_AZURE_AI_FOUNDRY_OPENAI_V1_API_VERSIONS = frozenset({"v1", "preview"})


# Azure AI Foundry validation functions
def _build_azure_ai_foundry_url(
    endpoint: str, target_subpath: str = "", api_version: str | None = None
) -> str:
    """Build a valid Azure AI Foundry URL with target subpath and api-version parameter.

    Foundry hands out (at least) two incompatible endpoint forms, and this
    branches on which one `endpoint` already targets:

    - **OpenAI-compatible** (`.../openai/v1`): the target subpath (e.g.
      `/chat/completions`) is appended directly with NO `/models` segment and
      NO dated api-version — this route is path-versioned and Azure rejects a
      dated `api-version` value here (only the literal "v1"/"preview" are
      valid, and only for the `/models` listing route, never for actual
      chat/embedding calls). Sending a `/models`-prefixed path here 404s
      ("deployment not found") because that route doesn't exist on this form.
    - **Everything else** (generic model-inference, or a "Microsoft Foundry"
      project endpoint like `.../api/projects/<project>`): always resolves
      under a `/models` segment (e.g. `.../models/chat/completions`) —
      LiteLLM's azure_ai handler unconditionally inserts that segment for any
      `services.ai.azure.com` host (see `get_complete_url` in
      litellm/llms/azure_ai/chat/transformation.py), so a project endpoint
      resolves to `.../api/projects/<project>/models/chat/completions`, not
      `.../chat/completions` (the latter 404s: that flat route doesn't exist
      on project-based resources). An explicit `api_version` always wins over
      whatever is embedded in `endpoint`; absent both, defaults to
      AZURE_AI_FOUNDRY_DEFAULT_API_VERSION — this form rejects requests with
      no api-version at all.

    Segment overlap is deduped either way so an endpoint that already ends in
    the target segment doesn't get a duplicate.
    """
    if not endpoint:
        return endpoint

    clean_endpoint = endpoint.strip()
    parsed = urlparse(clean_endpoint)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc or (parsed.path.split("/")[0] if parsed.path else "")
    path = (
        parsed.path
        if parsed.scheme
        else ("/" + "/".join(parsed.path.split("/")[1:]) if "/" in parsed.path else parsed.path)
    )

    base_path = path.rstrip("/")
    base_segments = [s for s in base_path.split("/") if s]
    is_openai_v1 = [s.lower() for s in base_segments[-2:]] == ["openai", "v1"]
    query_params = parse_qs(parsed.query, keep_blank_values=True)

    if is_openai_v1:
        # /models is the only sub-route documented for this form outside of
        # actual inference; treat a blank target_subpath (the credential
        # health-check probe) as "list models" rather than the bare /openai/v1
        # root, mirroring the generic form's "empty subpath -> /models" below.
        end_segments = [s for s in target_subpath.split("/") if s] or ["models"]
        new_path = "/" + "/".join(base_segments + end_segments)
        existing_versions = [
            v for v in query_params.get("api-version", []) if v in _AZURE_AI_FOUNDRY_OPENAI_V1_API_VERSIONS
        ]
        if existing_versions:
            query_params["api-version"] = existing_versions
        elif api_version in _AZURE_AI_FOUNDRY_OPENAI_V1_API_VERSIONS:
            query_params["api-version"] = [api_version]
        else:
            query_params.pop("api-version", None)
        query_params.pop("api_version", None)
    else:
        ending_path = f"/models{target_subpath}" if target_subpath else "/models"
        new_path = _merge_azure_ai_foundry_path(base_path, ending_path)
        if api_version:
            query_params["api-version"] = [api_version]
            query_params.pop("api_version", None)
        elif "api-version" not in query_params and "api_version" not in query_params:
            query_params["api-version"] = [AZURE_AI_FOUNDRY_DEFAULT_API_VERSION]

    new_query = urlencode(query_params, doseq=True)
    return urlunparse((scheme, netloc, new_path, parsed.params, new_query, parsed.fragment))


async def _test_azure_ai_foundry_lightweight_health(
    api_key: str, endpoint: str, api_version: str | None = None
) -> None:
    """Test Azure AI Foundry credentials with a lightweight GET to the models endpoint."""
    if not api_key:
        raise Exception("Azure AI Foundry API key is required.")
    if not endpoint:
        raise Exception("Azure AI Foundry endpoint URL is required.")

    try:
        health_url = _build_azure_ai_foundry_url(endpoint, api_version=api_version)
        logger.info(f"Azure AI Foundry health check request URL: {health_url}")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "api-key": api_key,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(
                health_url,
                headers=headers,
                timeout=10.0,
            )
            if response.status_code == 401:
                raise Exception("Invalid API key. Verify the key in Azure AI Foundry portal.")
            if response.status_code == 403:
                raise Exception("Access denied. Verify the API key has the required permissions.")
            # 200 or 404 (empty catalog) both confirm the endpoint is reachable and the key is accepted.
            logger.info("Azure AI Foundry lightweight health check passed")

    except httpx.TimeoutException:
        logger.error("Azure AI Foundry health check timed out")
        raise Exception(
            "Azure AI Foundry endpoint did not respond. Check the endpoint URL."
        ) from None
    except Exception as e:
        logger.error(f"Azure AI Foundry health check failed: {str(e)}")
        raise


async def _test_azure_ai_foundry_completion(
    api_key: str, llm_model: str, endpoint: str, api_version: str | None = None
) -> None:
    """Test Azure AI Foundry chat completion with the given deployment."""
    if not api_key:
        raise Exception("Azure AI Foundry API key is required.")
    if not endpoint:
        raise Exception("Azure AI Foundry endpoint URL is required.")
    if not llm_model:
        raise Exception("A deployment name is required to test Azure AI Foundry completion.")

    try:
        completions_url = _build_azure_ai_foundry_url(
            endpoint, "/chat/completions", api_version=api_version
        )
        logger.info(f"Azure AI Foundry completion request URL: {completions_url}")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "api-key": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "model": llm_model,
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 10,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                completions_url,
                headers=headers,
                json=payload,
                timeout=30.0,
            )
            if response.status_code != 200:
                error_details = _extract_error_details(response)
                if response.status_code == 401:
                    raise Exception("Invalid API key. Verify the key in Azure AI Foundry portal.")
                if response.status_code == 403:
                    raise Exception(
                        "Access denied. Verify the API key has the required permissions."
                    )
                if response.status_code == 404:
                    raise Exception(
                        f"Deployment '{llm_model}' not found. Check that the deployment name matches exactly what was created in Azure AI Foundry."
                    )
                if response.status_code == 429:
                    raise Exception("Azure AI Foundry rate limit exceeded.")
                raise Exception(f"Azure AI Foundry API error: {error_details}")
            logger.info("Azure AI Foundry completion test passed")

    except httpx.TimeoutException:
        logger.error("Azure AI Foundry completion test timed out")
        raise Exception("Request timed out") from None
    except Exception as e:
        logger.error(f"Azure AI Foundry completion test failed: {str(e)}")
        raise


async def _test_azure_ai_foundry_embedding(
    api_key: str, embedding_model: str, endpoint: str, api_version: str | None = None
) -> None:
    """Test Azure AI Foundry embedding generation with the given deployment."""
    if not api_key:
        raise Exception("Azure AI Foundry API key is required.")
    if not endpoint:
        raise Exception("Azure AI Foundry endpoint URL is required.")
    if not embedding_model:
        raise Exception("A deployment name is required to test Azure AI Foundry embeddings.")

    try:
        embeddings_url = _build_azure_ai_foundry_url(
            endpoint, "/embeddings", api_version=api_version
        )
        logger.info(f"Azure AI Foundry embedding request URL: {embeddings_url}")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "api-key": api_key,
            "Content-Type": "application/json",
        }
        payload = {"model": embedding_model, "input": ["test"]}
        async with httpx.AsyncClient() as client:
            response = await client.post(
                embeddings_url,
                headers=headers,
                json=payload,
                timeout=30.0,
            )
            if response.status_code != 200:
                error_details = _extract_error_details(response)
                if response.status_code == 401:
                    raise Exception("Invalid API key. Verify the key in Azure AI Foundry portal.")
                if response.status_code == 404:
                    raise Exception(
                        f"Embedding deployment '{embedding_model}' not found. Check that the deployment name matches exactly what was created in Azure AI Foundry."
                    )
                if response.status_code == 429:
                    raise Exception("Azure AI Foundry rate limit exceeded.")
                raise Exception(f"Azure AI Foundry embedding error: {error_details}")
            logger.info("Azure AI Foundry embedding test passed")

    except httpx.TimeoutException:
        logger.error("Azure AI Foundry embedding test timed out")
        raise Exception("Request timed out") from None
    except Exception as e:
        logger.error(f"Azure AI Foundry embedding test failed: {str(e)}")
        raise


# Azure OpenAI Service validation functions
def _azure_openai_base(endpoint: str) -> str:
    """Normalize an Azure OpenAI endpoint to its resource base (no trailing slash).

    Delegates to the shared helper so validation and LiteLLM inference build the
    request URL from the exact same normalized base.
    """
    return normalize_azure_openai_base(endpoint)


async def _test_azure_openai_lightweight_health(
    api_key: str, endpoint: str, api_version: str
) -> None:
    """Test Azure OpenAI credentials with a lightweight GET to the models list.

    Uses the data-plane models list which validates the key + endpoint without
    consuming credits.
    """
    if not api_key:
        raise Exception("Azure OpenAI API key is required.")
    if not endpoint:
        raise Exception("Azure OpenAI endpoint URL is required.")
    if not api_version:
        raise Exception("Azure OpenAI API version is required.")

    try:
        models_url = f"{_azure_openai_base(endpoint)}/openai/models?api-version={api_version}"
        async with httpx.AsyncClient() as client:
            response = await client.get(
                models_url,
                headers={"api-key": api_key, "Content-Type": "application/json"},
                timeout=10.0,
            )
            if response.status_code == 401:
                raise Exception("Invalid API key. Verify the key in the Azure portal.")
            if response.status_code == 403:
                raise Exception("Access denied. Verify the API key has the required permissions.")
            if response.status_code == 404:
                raise Exception(
                    "Azure OpenAI endpoint not found. Check the endpoint URL and API version."
                )
            if response.status_code >= 400:
                error_details = _extract_error_details(response)
                raise Exception(f"Azure OpenAI API error: {error_details}")
            logger.info("Azure OpenAI lightweight health check passed")

    except httpx.TimeoutException:
        logger.error("Azure OpenAI health check timed out")
        raise Exception("Azure OpenAI endpoint did not respond. Check the endpoint URL.") from None
    except Exception as e:
        logger.error(f"Azure OpenAI health check failed: {str(e)}")
        raise


async def _test_azure_openai_completion(
    api_key: str, llm_model: str, endpoint: str, api_version: str
) -> None:
    """Test Azure OpenAI chat completion with the given deployment.

    Azure OpenAI takes the deployment name in the URL path (not the request body)
    and requires an api-version query parameter.
    """
    if not api_key:
        raise Exception("Azure OpenAI API key is required.")
    if not endpoint:
        raise Exception("Azure OpenAI endpoint URL is required.")
    if not api_version:
        raise Exception("Azure OpenAI API version is required.")
    if not llm_model:
        raise Exception("A deployment name is required to test Azure OpenAI completion.")

    try:
        completions_url = (
            f"{_azure_openai_base(endpoint)}/openai/deployments/{llm_model}"
            f"/chat/completions?api-version={api_version}"
        )
        payload = {
            "messages": [{"role": "user", "content": "Hello"}],
            "max_completion_tokens": 10,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                completions_url,
                headers={"api-key": api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=30.0,
            )
            # Some deployments reject max_completion_tokens; retry with max_tokens.
            if response.status_code == 400:
                payload = {
                    "messages": [{"role": "user", "content": "Hello"}],
                    "max_tokens": 10,
                }
                response = await client.post(
                    completions_url,
                    headers={"api-key": api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=30.0,
                )
            if response.status_code != 200:
                error_details = _extract_error_details(response)
                if response.status_code == 401:
                    raise Exception("Invalid API key. Verify the key in the Azure portal.")
                if response.status_code == 403:
                    raise Exception(
                        "Access denied. Verify the API key has the required permissions."
                    )
                if response.status_code == 404:
                    raise Exception(
                        f"Deployment '{llm_model}' not found. Check that the deployment name matches "
                        "exactly what was created in Azure OpenAI, and that the API version is correct."
                    )
                if response.status_code == 429:
                    raise Exception("Azure OpenAI rate limit exceeded.")
                raise Exception(f"Azure OpenAI API error: {error_details}")
            logger.info("Azure OpenAI completion test passed")

    except httpx.TimeoutException:
        logger.error("Azure OpenAI completion test timed out")
        raise Exception("Request timed out") from None
    except Exception as e:
        logger.error(f"Azure OpenAI completion test failed: {str(e)}")
        raise


async def _test_azure_openai_embedding(
    api_key: str, embedding_model: str, endpoint: str, api_version: str
) -> None:
    """Test Azure OpenAI embedding generation with the given deployment."""
    if not api_key:
        raise Exception("Azure OpenAI API key is required.")
    if not endpoint:
        raise Exception("Azure OpenAI endpoint URL is required.")
    if not api_version:
        raise Exception("Azure OpenAI API version is required.")
    if not embedding_model:
        raise Exception("A deployment name is required to test Azure OpenAI embeddings.")

    try:
        embeddings_url = (
            f"{_azure_openai_base(endpoint)}/openai/deployments/{embedding_model}"
            f"/embeddings?api-version={api_version}"
        )
        payload = {"input": ["test"]}
        async with httpx.AsyncClient() as client:
            response = await client.post(
                embeddings_url,
                headers={"api-key": api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=30.0,
            )
            if response.status_code != 200:
                error_details = _extract_error_details(response)
                if response.status_code == 401:
                    raise Exception("Invalid API key. Verify the key in the Azure portal.")
                if response.status_code == 404:
                    raise Exception(
                        f"Embedding deployment '{embedding_model}' not found. Check that the "
                        "deployment name matches exactly what was created in Azure OpenAI, and "
                        "that the API version is correct."
                    )
                if response.status_code == 429:
                    raise Exception("Azure OpenAI rate limit exceeded.")
                raise Exception(f"Azure OpenAI embedding error: {error_details}")
            logger.info("Azure OpenAI embedding test passed")

    except httpx.TimeoutException:
        logger.error("Azure OpenAI embedding test timed out")
        raise Exception("Request timed out") from None
    except Exception as e:
        logger.error(f"Azure OpenAI embedding test failed: {str(e)}")
        raise
