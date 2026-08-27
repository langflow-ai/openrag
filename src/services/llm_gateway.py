"""OpenAI-compatible LLM gateway backed by the LiteLLM SDK.

Langflow and other OpenAI clients call `/v1/chat/completions` and
`/v1/embeddings`. This module owns provider secrets (from OpenRAG config) and
routes by model prefix / configured provider. Callers never see upstream keys.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any, Literal

from services.model_catalog import is_known_provider
from utils.logging_config import get_logger

logger = get_logger(__name__)

_LITELLM_FORWARDED_PARAMS = (
    "tools",
    "tool_choice",
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "stop",
    "presence_penalty",
    "frequency_penalty",
    "seed",
    "response_format",
    "parallel_tool_calls",
    "n",
    "user",
    "logit_bias",
    "stream_options",
)


class LlmGatewayError(Exception):
    """Gateway failure. `status_code` is an HTTP status.

    `message` is safe to return to the caller. `detail` carries the internal
    text (upstream exception type and body) and is for logs only — returning it
    is stack-trace exposure (CodeQL py/stack-trace-exposure).
    """

    def __init__(self, message: str, status_code: int = 400, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail or message


def _get_config():
    from config.settings import get_openrag_config

    return get_openrag_config()


#: Canonical separator between an OpenRAG provider tag and the model id.
#: `/` cannot serve as one: watsonx hosts `openai/gpt-oss-120b`, whose own name
#: begins with a provider key, so a `/`-split routes it to OpenAI and LiteLLM
#: then rejects the bare `gpt-oss-120b`. No catalogue id has a provider-shaped
#: prefix before a colon, so `provider:model` stays unambiguous even for ids
#: that use colons themselves (`ollama:gpt-oss:120b-cloud`, `openai:ft:gpt-4`).
PROVIDER_SEPARATOR = ":"


def split_model_id(model: str) -> tuple[str | None, str]:
    """Split an OpenRAG provider tag off a model id.

    `provider:model` is the canonical form and is checked first. `provider/`
    is still accepted so ids stored before the switch keep resolving, but only
    when the remainder does not look like a provider-qualified name itself.
    """
    raw = (model or "").strip()

    prefix, sep, rest = raw.partition(PROVIDER_SEPARATOR)
    if sep and rest:
        prefix_lower = prefix.lower()
        if is_known_provider(prefix_lower):
            return prefix_lower, rest

    if "/" not in raw:
        return None, raw

    # A slash is ambiguous: it separates a legacy tag from its model, but it is
    # also part of vendor-qualified names. When the whole string names exactly
    # one catalogue model, that provider owns it — `openai/gpt-oss-120b` is
    # watsonx's model, not OpenAI's `gpt-oss-120b`.
    from services.model_catalog import catalog_owner

    owner = catalog_owner(raw)
    if owner:
        return owner, raw

    prefix, rest = raw.split("/", 1)
    prefix_lower = prefix.lower()
    if is_known_provider(prefix_lower):
        return prefix_lower, rest
    return None, raw


def default_provider(kind: Literal["chat", "embedding"], config=None) -> str:
    cfg = config or _get_config()
    if kind == "embedding":
        return (cfg.knowledge.embedding_provider or "openai").lower()
    return (cfg.agent.llm_provider or "openai").lower()


def default_model(kind: Literal["chat", "embedding"], config=None) -> str:
    cfg = config or _get_config()
    if kind == "embedding":
        return cfg.knowledge.embedding_model or ""
    return cfg.agent.llm_model or ""


def provider_credentials(provider: str, config=None) -> dict[str, Any]:
    """LiteLLM kwargs for any configured OpenRAG provider. Never logs secrets."""
    cfg = config or _get_config()
    key = (provider or "").strip().lower()
    try:
        prov = cfg.providers
    except Exception as exc:
        raise LlmGatewayError("LLM providers are not configured", 400) from exc

    if hasattr(prov, "credential_values"):
        credentials = prov.credential_values(key)
    else:
        provider_config = getattr(prov, key, None)
        if provider_config is None:
            credentials = {}
        elif key == "watsonx":
            credentials = {
                name: value
                for name, value in {
                    "api_key": getattr(provider_config, "api_key", None),
                    "api_base": getattr(provider_config, "endpoint", None),
                    "project_id": getattr(provider_config, "project_id", None),
                }.items()
                if value
            }
        elif key == "ollama":
            endpoint = getattr(provider_config, "resolved_endpoint", None) or getattr(
                provider_config, "endpoint", None
            )
            credentials = {"api_base": endpoint} if endpoint else {}
        else:
            api_key = getattr(provider_config, "api_key", None)
            credentials = {"api_key": api_key} if api_key else {}
    if key == "ollama" and credentials.get("api_base"):
        from utils.container_utils import transform_localhost_url

        credentials["api_base"] = transform_localhost_url(str(credentials["api_base"]))
    custom = getattr(prov, "custom", {})
    custom_config = custom.get(key) if isinstance(custom, dict) else None
    configured = bool(getattr(custom_config, "configured", False))
    if not credentials and not configured:
        raise LlmGatewayError(
            f"Provider {key!r} is not configured in OpenRAG. "
            "Configure it in Settings or pick a model from a configured provider.",
            400,
        )
    return credentials


def resolve_call(
    model: str | None,
    *,
    kind: Literal["chat", "embedding"],
    config=None,
) -> tuple[str, str, dict[str, Any]]:
    """Return `(litellm_model, provider, credentials)` for a request model id."""
    cfg = config or _get_config()
    requested = (model or "").strip() or default_model(kind, cfg)
    if not requested:
        raise LlmGatewayError("model is required", 400)

    provider, name = split_model_id(requested)
    if provider is None:
        provider = default_provider(kind, cfg)
        name = requested
    credentials = provider_credentials(provider, cfg)
    litellm_model = f"{provider}/{name}" if provider != "openai" else name
    return litellm_model, provider, credentials


_UPSTREAM_FAILURE_MESSAGE = "The model provider could not be reached. Please try again."
_UPSTREAM_CREDENTIAL_MESSAGE = (
    "The configured API key is invalid or has been revoked. Update it in Settings and retry."
)


def _upstream_client_message(detail: str) -> str:
    """Safe client text for an upstream failure.

    The upstream text is only *classified*, never forwarded: both return values
    are fixed literals, so provider internals and traceback text cannot reach
    the caller (CodeQL py/stack-trace-exposure). A credential failure still gets
    its own actionable message so onboarding can tell the user to fix the key.
    """
    from api.provider_validation import is_provider_credential_error

    if is_provider_credential_error(detail):
        return _UPSTREAM_CREDENTIAL_MESSAGE
    return _UPSTREAM_FAILURE_MESSAGE


def _redact(message: str, credentials: Mapping[str, Any]) -> str:
    redacted = message
    for value in credentials.values():
        if value and isinstance(value, str) and len(value) > 3:
            redacted = redacted.replace(value, "[redacted]")
    return redacted


def _to_openai_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        dumped = response.model_dump()
        if isinstance(dumped, dict):
            return dumped
    if hasattr(response, "json"):
        payload = response.json()
        if isinstance(payload, str):
            return json.loads(payload)
        if isinstance(payload, dict):
            return payload
    return dict(response)


def _chunk_payload(chunk: Any) -> str:
    if hasattr(chunk, "model_dump_json"):
        return chunk.model_dump_json()
    if hasattr(chunk, "json"):
        payload = chunk.json()
        return payload if isinstance(payload, str) else json.dumps(payload)
    if isinstance(chunk, dict):
        return json.dumps(chunk)
    return json.dumps({"data": str(chunk)})


def _log_completion_shape(payload: dict[str, Any], provider: str, model: str) -> None:
    """Record the shape of a non-streaming completion.

    An empty completion is indistinguishable from a transport failure once it
    reaches Langflow: the agent simply ends its loop and the user sees "The
    server didn't return a response". Only metadata is logged — never message
    content — so this stays safe to leave on.
    """
    try:
        choices = payload.get("choices") or []
        first = choices[0] if choices else {}
        message = first.get("message") or {}
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []
        finish_reason = first.get("finish_reason")
        empty = not str(content).strip() and not tool_calls
        log = logger.warning if empty else logger.info
        log(
            "LLM chat completion returned no content and no tool calls"
            if empty
            else "LLM chat completion",
            provider=provider,
            model=model,
            finish_reason=finish_reason,
            content_chars=len(str(content)),
            tool_calls=len(tool_calls),
            choices=len(choices),
        )
    except Exception:  # diagnostics must never break a response
        logger.debug("Could not summarise completion shape", exc_info=True)


async def chat_completions(
    body: Mapping[str, Any], *, config=None
) -> dict[str, Any] | AsyncIterator[str]:
    """OpenAI `POST /v1/chat/completions`. Streams SSE lines when `stream` is true."""
    cfg = config or _get_config()
    litellm_model, provider, credentials = resolve_call(body.get("model"), kind="chat", config=cfg)
    kwargs = {key: body[key] for key in _LITELLM_FORWARDED_PARAMS if key in body}
    stream = bool(body.get("stream"))
    try:
        import litellm

        result = await litellm.acompletion(
            model=litellm_model,
            messages=list(body.get("messages") or []),
            stream=stream,
            # OpenAI-compatible clients send OpenAI's full parameter set, but
            # providers accept different subsets — watsonx rejects
            # `parallel_tool_calls`, `max_completion_tokens` and `logit_bias`,
            # and LiteLLM raises UnsupportedParamsError rather than ignoring
            # them. A proxy that fans out to many providers must degrade to the
            # provider's capabilities instead of failing the request.
            drop_params=True,
            **credentials,
            **kwargs,
        )
    except LlmGatewayError:
        raise
    except Exception as exc:
        detail = _redact(f"{type(exc).__name__}: {exc}", credentials)
        logger.error("LLM chat completions failed", provider=provider, error=detail)
        raise LlmGatewayError(_upstream_client_message(detail), 502, detail=detail) from exc

    if stream:
        return _stream_sse(result, provider, litellm_model)
    payload = _to_openai_dict(result)
    _log_completion_shape(payload, provider, litellm_model)
    return payload


class _StreamTally:
    """Running totals for one streamed completion. Metadata only, no content."""

    def __init__(self) -> None:
        self.chunks = 0
        self.content_chars = 0
        self.tool_calls = 0
        self.finish_reason: str | None = None

    def observe(self, payload: str) -> None:
        try:
            chunk = json.loads(payload)
        except Exception:
            return
        self.chunks += 1
        for choice in chunk.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            if choice.get("finish_reason"):
                self.finish_reason = choice["finish_reason"]
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if isinstance(content, str):
                self.content_chars += len(content)
            self.tool_calls += len(delta.get("tool_calls") or [])


async def _stream_sse(stream: Any, provider: str = "", model: str = "") -> AsyncIterator[str]:
    tally = _StreamTally()
    try:
        if hasattr(stream, "__aiter__"):
            async for chunk in stream:
                payload = _chunk_payload(chunk)
                tally.observe(payload)
                yield f"data: {payload}\n\n"
        else:
            for chunk in stream:
                payload = _chunk_payload(chunk)
                tally.observe(payload)
                yield f"data: {payload}\n\n"
    finally:
        close = getattr(stream, "aclose", None) or getattr(stream, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
        _log_stream_shape(tally, provider, model)
    yield "data: [DONE]\n\n"


def _log_stream_shape(tally: _StreamTally, provider: str, model: str) -> None:
    """Same diagnostic as `_log_completion_shape`, for the streaming path."""
    try:
        empty = tally.content_chars == 0 and tally.tool_calls == 0
        log = logger.warning if empty else logger.info
        log(
            "LLM chat stream produced no content and no tool calls" if empty else "LLM chat stream",
            provider=provider,
            model=model,
            finish_reason=tally.finish_reason,
            content_chars=tally.content_chars,
            tool_calls=tally.tool_calls,
            chunks=tally.chunks,
        )
    except Exception:  # diagnostics must never break a stream
        logger.debug("Could not summarise stream shape", exc_info=True)


async def embeddings(body: Mapping[str, Any], *, config=None) -> dict[str, Any]:
    """OpenAI `POST /v1/embeddings`."""
    cfg = config or _get_config()
    litellm_model, provider, credentials = resolve_call(
        body.get("model"), kind="embedding", config=cfg
    )
    try:
        import litellm

        result = await litellm.aembedding(
            model=litellm_model,
            input=body.get("input"),
            **credentials,
        )
    except LlmGatewayError:
        raise
    except Exception as exc:
        detail = _redact(f"{type(exc).__name__}: {exc}", credentials)
        logger.error("LLM embeddings failed", provider=provider, error=detail)
        raise LlmGatewayError(_upstream_client_message(detail), 502, detail=detail) from exc
    return _to_openai_dict(result)
