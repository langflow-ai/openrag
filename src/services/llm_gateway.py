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

_KNOWN_PREFIXES = ("openai", "anthropic", "ollama", "watsonx")

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
    """User-facing gateway failure. `status_code` is an HTTP status."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _get_config():
    from config.settings import get_openrag_config

    return get_openrag_config()


def split_model_id(model: str) -> tuple[str | None, str]:
    """Split `provider/name` when the prefix is a known LiteLLM provider."""
    raw = (model or "").strip()
    if "/" not in raw:
        return None, raw
    prefix, rest = raw.split("/", 1)
    prefix_lower = prefix.lower()
    if prefix_lower in _KNOWN_PREFIXES or is_known_provider(prefix_lower):
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
    """LiteLLM kwargs for a configured OpenRAG provider. Never logs secrets."""
    cfg = config or _get_config()
    key = (provider or "").strip().lower()
    try:
        prov = cfg.providers
    except Exception as exc:
        raise LlmGatewayError("LLM providers are not configured", 400) from exc

    if key == "openai":
        api_key = getattr(prov.openai, "api_key", None)
        if not api_key:
            raise LlmGatewayError("OpenAI API key is not configured", 400)
        return {"api_key": api_key}
    if key == "anthropic":
        api_key = getattr(prov.anthropic, "api_key", None)
        if not api_key:
            raise LlmGatewayError("Anthropic API key is not configured", 400)
        return {"api_key": api_key}
    if key == "ollama":
        endpoint = getattr(prov.ollama, "resolved_endpoint", None) or getattr(
            prov.ollama, "endpoint", None
        )
        if not endpoint:
            raise LlmGatewayError("Ollama endpoint is not configured", 400)
        from utils.container_utils import transform_localhost_url

        return {"api_base": transform_localhost_url(str(endpoint))}
    if key in {"watsonx", "watsonx_text"}:
        watsonx = prov.watsonx
        api_key = getattr(watsonx, "api_key", None)
        endpoint = getattr(watsonx, "endpoint", None)
        project_id = getattr(watsonx, "project_id", None)
        if not api_key:
            raise LlmGatewayError("WatsonX API key is not configured", 400)
        if not endpoint:
            raise LlmGatewayError("WatsonX endpoint is not configured", 400)
        if not project_id:
            raise LlmGatewayError("WatsonX project ID is not configured", 400)
        return {"api_key": api_key, "api_base": endpoint, "project_id": project_id}

    raise LlmGatewayError(
        f"Provider {key!r} is not configured in OpenRAG. "
        "Configure it in Settings or pick a model from a configured provider.",
        400,
    )


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


async def chat_completions(body: Mapping[str, Any], *, config=None) -> dict[str, Any] | AsyncIterator[str]:
    """OpenAI `POST /v1/chat/completions`. Streams SSE lines when `stream` is true."""
    cfg = config or _get_config()
    litellm_model, provider, credentials = resolve_call(
        body.get("model"), kind="chat", config=cfg
    )
    kwargs = {key: body[key] for key in _LITELLM_FORWARDED_PARAMS if key in body}
    stream = bool(body.get("stream"))
    try:
        import litellm

        result = await litellm.acompletion(
            model=litellm_model,
            messages=list(body.get("messages") or []),
            stream=stream,
            **credentials,
            **kwargs,
        )
    except LlmGatewayError:
        raise
    except Exception as exc:
        message = _redact(f"{type(exc).__name__}: {exc}", credentials)
        logger.error("LLM chat completions failed", provider=provider, error=message)
        raise LlmGatewayError(message, 502) from exc

    if stream:
        return _stream_sse(result)
    return _to_openai_dict(result)


async def _stream_sse(stream: Any) -> AsyncIterator[str]:
    try:
        if hasattr(stream, "__aiter__"):
            async for chunk in stream:
                yield f"data: {_chunk_payload(chunk)}\n\n"
        else:
            for chunk in stream:
                yield f"data: {_chunk_payload(chunk)}\n\n"
    finally:
        close = getattr(stream, "aclose", None) or getattr(stream, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
    yield "data: [DONE]\n\n"


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
        message = _redact(f"{type(exc).__name__}: {exc}", credentials)
        logger.error("LLM embeddings failed", provider=provider, error=message)
        raise LlmGatewayError(message, 502) from exc
    return _to_openai_dict(result)
