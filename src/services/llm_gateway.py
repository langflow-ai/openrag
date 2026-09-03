"""OpenAI-compatible LLM gateway backed by the LiteLLM SDK.

Langflow and other OpenAI clients call `/v1/chat/completions` and
`/v1/embeddings`. This module owns provider secrets (from OpenRAG config) and
routes by model prefix / configured provider. Callers never see upstream keys.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Mapping
from typing import Any, Literal

from config.model_providers import canonical_provider
from services import provider_error_log
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
LEGACY_EMBEDDING_MODEL_PREFIX = "legacy:"
INDEXED_EMBEDDING_SPACE_PREFIX = "space:"
_BUILTIN_LEGACY_EMBEDDING_PROVIDERS = {
    "text-embedding-3-small": "openai",
}


def split_model_id(model: str) -> tuple[str | None, str]:
    """Split an OpenRAG provider tag off a model id.

    `provider:model` is the canonical form and is checked first. `provider/`
    is still accepted so ids stored before the switch keep resolving, but only
    when the remainder does not look like a provider-qualified name itself.
    """
    raw = (model or "").strip()

    prefix, sep, rest = raw.partition(PROVIDER_SEPARATOR)
    if sep and rest:
        prefix_lower = canonical_provider(prefix)
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
    prefix_lower = canonical_provider(prefix)
    if is_known_provider(prefix_lower):
        return prefix_lower, rest
    return None, raw


def default_provider(kind: Literal["chat", "embedding"], config=None) -> str:
    cfg = config or _get_config()
    if kind == "embedding":
        return canonical_provider(cfg.knowledge.embedding_provider or "openai")
    return canonical_provider(cfg.agent.llm_provider or "openai")


def default_model(kind: Literal["chat", "embedding"], config=None) -> str:
    cfg = config or _get_config()
    if kind == "embedding":
        return cfg.knowledge.embedding_model or ""
    return cfg.agent.llm_model or ""


def legacy_embedding_provider(model: str, config: Any | None = None) -> str | None:
    """Resolve provenance for a model-only embedding space from before provider tracking."""
    name = (model or "").strip()
    if name in _BUILTIN_LEGACY_EMBEDDING_PROVIDERS:
        return _BUILTIN_LEGACY_EMBEDDING_PROVIDERS[name]

    cfg = config or _get_config()
    mapping = getattr(cfg.knowledge, "legacy_embedding_provider_map", {}) or {}
    if not isinstance(mapping, Mapping):
        return None
    provider = canonical_provider(str(mapping.get(name) or ""))
    return provider or None


def provider_credentials(provider: str, config=None) -> dict[str, Any]:
    """LiteLLM kwargs for any configured OpenRAG provider. Never logs secrets."""
    cfg = config or _get_config()
    key = canonical_provider(provider)
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

    if kind == "embedding" and requested.startswith(INDEXED_EMBEDDING_SPACE_PREFIX):
        space_id = requested[len(INDEXED_EMBEDDING_SPACE_PREFIX) :].strip()
        provider, separator, name = space_id.partition(PROVIDER_SEPARATOR)
        provider = canonical_provider(provider)
        name = name.strip()
        if not separator or not provider or not name:
            raise LlmGatewayError(
                f"Indexed embedding space {space_id!r} has no exact provider route.",
                400,
            )
    elif kind == "embedding" and requested.startswith(LEGACY_EMBEDDING_MODEL_PREFIX):
        name = requested[len(LEGACY_EMBEDDING_MODEL_PREFIX) :].strip()
        provider = legacy_embedding_provider(name, cfg)
        if not provider:
            raise LlmGatewayError(
                f"Legacy embedding model {name!r} has no provider mapping. "
                "Set knowledge.legacy_embedding_provider_map for this model.",
                400,
            )
    else:
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


#: Longest upstream explanation we will echo. Provider bodies can embed a whole
#: model catalogue; past this the message stops being readable in a chat bubble.
_MAX_UPSTREAM_MESSAGE_CHARS = 600

#: Lines LiteLLM appends to its own exceptions that say nothing about the failure.
_UPSTREAM_NOISE_MARKERS = (
    "Give Feedback / Get Help",
    "LiteLLM.Info:",
    "For more information check:",
    "For further information visit",
    "During handling of the above exception",
)

#: Everything from here on is interpreter state, not provider explanation.
_TRACEBACK_MARKERS = ("Traceback (most recent call last)", 'File "')

_FILE_PATH_PATTERN = re.compile(r"(?:/[\w.\-]+)+\.py")
#: Loopback and RFC1918 addresses — deployment topology, not provider explanation.
_PRIVATE_HOST_PATTERN = re.compile(
    r"\b(?:127(?:\.\d{1,3}){3}|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}"
    r"|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|localhost)\b"
)
_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


def _call_label(provider: str, model: str) -> str:
    """`provider/model` for humans, without repeating a prefix LiteLLM already added."""
    if model and provider and not model.startswith(f"{provider}/"):
        return f"{provider}/{model}"
    return model or provider or "provider"


def _json_bodies(text: str):
    """Yield every JSON object embedded in `text`, outermost first."""
    decoder = json.JSONDecoder()
    index = text.find("{")
    while index != -1:
        try:
            body, end = decoder.raw_decode(text, index)
        except ValueError:
            index = text.find("{", index + 1)
            continue
        yield body
        index = text.find("{", end)


def _provider_message(body: Any) -> str | None:
    """The provider's own explanation out of one parsed error body."""
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    if isinstance(error, str) and error.strip():
        return error
    errors = body.get("errors")
    if isinstance(errors, list):
        parts = [
            item["message"]
            for item in errors
            if isinstance(item, dict) and isinstance(item.get("message"), str)
        ]
        if parts:
            return "; ".join(parts)
    for key in ("message", "detail"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _is_provider_attributable(exc: BaseException | None) -> bool:
    """True when the failure came from the provider call, not from our own code.

    Anything LiteLLM raises describes the upstream request — it tags its
    exceptions with `llm_provider`, and its transport wrappers live under the
    `litellm` package. A `RuntimeError` from OpenRAG code does not, and its text
    is ours to keep in the logs.
    """
    if exc is None:
        return False
    if getattr(exc, "llm_provider", None):
        return True
    return type(exc).__module__.split(".")[0] == "litellm"


def _sanitise_upstream_detail(detail: str) -> str:
    """Strip interpreter state out of an upstream failure, keep the explanation.

    Traceback frames, local file paths, private addresses and LiteLLM's own
    footer chatter are removed; what is left is collapsed and capped so it fits
    a chat bubble. Credentials are already redacted by `_redact` before this
    runs.
    """
    text = _ANSI_PATTERN.sub("", detail or "")
    for marker in _TRACEBACK_MARKERS:
        cut = text.find(marker)
        if cut != -1:
            text = text[:cut]
    text = "\n".join(
        line
        for line in text.splitlines()
        if not any(marker in line for marker in _UPSTREAM_NOISE_MARKERS)
    )
    text = _FILE_PATH_PATTERN.sub("<path>", text)
    text = _PRIVATE_HOST_PATTERN.sub("<host>", text)
    text = " ".join(text.split())
    if len(text) > _MAX_UPSTREAM_MESSAGE_CHARS:
        text = text[: _MAX_UPSTREAM_MESSAGE_CHARS - 1].rstrip() + "\u2026"
    return text


def _provider_error_text(detail: str, exc: BaseException | None) -> str | None:
    """The provider's own words for a failure, or None when we cannot attribute it.

    Providers explain themselves precisely — "Model 'x' is not supported for
    this environment", "api_key is invalid" — and collapsing that into a fixed
    literal leaves an operator with nothing to act on. But only text we can tie
    to the upstream call earns a trip to the client: a JSON error body the
    provider sent, or a LiteLLM exception, which always describes the request it
    made. Anything else stays in the logs.
    """
    for body in _json_bodies(detail or ""):
        message = _provider_message(body)
        if message:
            return message
    if _is_provider_attributable(exc):
        return detail
    return None


#: Upstream statuses worth passing through: a client can act on these itself.
#: Everything else becomes 502 — an upstream 401/403 must not read as an OpenRAG
#: auth failure, and an upstream 400 must not read as a bad request to us.
_PASSTHROUGH_UPSTREAM_STATUSES = frozenset({408, 429, 503, 504})


def _upstream_status_code(exc: BaseException) -> int:
    """HTTP status for a failed upstream call, from the provider's own where useful."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status in _PASSTHROUGH_UPSTREAM_STATUSES:
        return status
    return 502


def _upstream_client_message(
    detail: str, provider: str = "", model: str = "", exc: BaseException | None = None
) -> str:
    """Client-facing text for an upstream failure, naming the provider and cause.

    Nothing is forwarded raw. `_provider_error_text` decides whether the failure
    is the provider's to explain, and `_sanitise_upstream_detail` removes
    traceback frames, paths and private addresses from what it returns — so the
    caller sees the provider's own wording and which provider/model produced it,
    and an unattributable failure still collapses to a fixed literal. A
    credential failure keeps its actionable message so onboarding can tell the
    user to fix the key.
    """
    from api.provider_validation import is_generic_upstream_error, is_provider_credential_error

    label = _call_label(provider, model)
    if is_provider_credential_error(detail):
        return f"{_UPSTREAM_CREDENTIAL_MESSAGE} ({label})"
    upstream = _provider_error_text(detail, exc)
    upstream = _sanitise_upstream_detail(upstream) if upstream else ""
    if not upstream or is_generic_upstream_error(upstream):
        return f"{_UPSTREAM_FAILURE_MESSAGE} ({label})"
    # lgtm[py/stack-trace-exposure] — provider error text only; traceback frames,
    # file paths and private hosts are removed by _sanitise_upstream_detail.
    return f"{label}: {upstream}"


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


#: A payload wrapped more times than this is not a serialisation slip.
_MAX_ARGUMENT_UNWRAPS = 3


def _normalise_tool_arguments(value: Any) -> tuple[Any, bool]:
    """Return `(arguments, repaired)`, unwrapping arguments serialised twice.

    OpenAI's contract is that `function.arguments` is a string holding a JSON
    *object*. Some models serialise the object and then serialise that string
    again, sending `'"{\\"query\\": \\"x\\"}"'` where `'{"query": "x"}'` was
    meant (watsonx `ibm/granite-4-h-small` does this; its stablemates on the
    same deployment do not). Clients parse `arguments` exactly once, so they get
    a `str` where a mapping is required: langchain-core rejects the tool call,
    the agent sees no callable tool, and the run ends with no content at all.
    Unwrapping is keyed on the payload opening with a quote, which a real
    arguments object never does, so this is a no-op for well-behaved providers.
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value), True
    if not isinstance(value, str) or not value.lstrip().startswith('"'):
        return value, False
    candidate = value
    for _ in range(_MAX_ARGUMENT_UNWRAPS):
        try:
            decoded = json.loads(candidate)
        except ValueError:
            return value, False
        if not isinstance(decoded, str):
            return value, False
        candidate = decoded
        try:
            inner = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(inner, (dict, list)):
            return candidate, True
    return value, False


def _repair_tool_calls(tool_calls: Any, provider: str, model: str) -> int:
    """Normalise `arguments` on every tool call in place. Returns how many changed."""
    repaired = 0
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        arguments, changed = _normalise_tool_arguments(function.get("arguments"))
        if changed:
            function["arguments"] = arguments
            repaired += 1
    if repaired:
        logger.warning(
            "Repaired double-encoded tool call arguments",
            provider=provider,
            model=model,
            tool_calls=repaired,
        )
    return repaired


def _repair_completion_payload(payload: dict[str, Any], provider: str, model: str) -> int:
    repaired = 0
    for choice in payload.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict):
            repaired += _repair_tool_calls(message.get("tool_calls"), provider, model)
    return repaired


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


#: Models seen to refuse function tools alongside their own default reasoning
#: effort. OpenAI applies a non-none default to reasoning models and rejects
#: that combination on /v1/chat/completions; the remedy its error names is an
#: explicit "none". Learned from the first failure rather than assumed, so a
#: model that accepts the pair keeps its reasoning.
_TOOLS_NEED_REASONING_OFF: set[str] = set()


def _model_info(model: str) -> dict[str, Any]:
    """LiteLLM's row for `model`, by its full id or its bare name."""
    try:
        import litellm

        table = litellm.model_cost
        info = table.get(model) or table.get(model.rsplit("/", 1)[-1])
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def _is_reasoning_tool_conflict(detail: str) -> bool:
    """Whether a failure is the tools-plus-reasoning_effort rejection.

    Matched on the provider's own words. There is no capability flag for it —
    `supports_reasoning` and `supports_function_calling` are both true for the
    models that refuse the combination — so the failure itself is the only
    signal available.
    """
    lowered = (detail or "").lower()
    return "reasoning_effort" in lowered and "tool" in lowered


def _reasoning_off_retry(model: str, kwargs: dict[str, Any]) -> bool:
    """Set `reasoning_effort="none"` for a retry, if that can help here.

    False when the caller chose an effort itself — overriding a deliberate
    choice would be worse than the error — or when the model cannot take
    "none", in which case only the Responses API can serve tools for it.
    """
    if not kwargs.get("tools") or "reasoning_effort" in kwargs:
        return False
    if not _model_info(model).get("supports_none_reasoning_effort"):
        return False
    kwargs["reasoning_effort"] = "none"
    return True


async def chat_completions(
    body: Mapping[str, Any], *, config=None
) -> dict[str, Any] | AsyncIterator[str]:
    """OpenAI `POST /v1/chat/completions`. Streams SSE lines when `stream` is true."""
    cfg = config or _get_config()
    litellm_model, provider, credentials = resolve_call(body.get("model"), kind="chat", config=cfg)
    kwargs = {key: body[key] for key in _LITELLM_FORWARDED_PARAMS if key in body}
    stream = bool(body.get("stream"))
    if litellm_model in _TOOLS_NEED_REASONING_OFF:
        # Already learned about this model; do not spend a round-trip relearning.
        _reasoning_off_retry(litellm_model, kwargs)

    async def _call() -> Any:
        import litellm

        return await litellm.acompletion(
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

    try:
        try:
            result = await _call()
        except Exception as exc:
            # `drop_params` cannot help here: reasoning_effort is a supported
            # parameter, just not one this model accepts beside tools. Retry
            # once with the value the provider's own error asks for.
            if not _is_reasoning_tool_conflict(f"{exc}") or not _reasoning_off_retry(
                litellm_model, kwargs
            ):
                raise
            logger.info(
                "Retrying completion with reasoning_effort=none",
                provider=provider,
                model=litellm_model,
            )
            _TOOLS_NEED_REASONING_OFF.add(litellm_model)
            result = await _call()
    except LlmGatewayError:
        raise
    except Exception as exc:
        detail = _redact(f"{type(exc).__name__}: {exc}", credentials)
        logger.error(
            "LLM chat completions failed", provider=provider, model=litellm_model, error=detail
        )
        message = _upstream_client_message(detail, provider, litellm_model, exc)
        # The health banner otherwise reports whatever its own probe hit, which
        # is a different request and so often a different error. Hand it the
        # text this caller is being shown.
        provider_error_log.record_failure(provider, "chat", message)
        raise LlmGatewayError(
            message,
            _upstream_status_code(exc),
            detail=detail,
        ) from exc

    if stream:
        # A stream can still fail mid-flight, so _stream_sse clears the record
        # itself once the provider has actually delivered something.
        return _stream_sse(result, provider, litellm_model, credentials)
    provider_error_log.record_success(provider, "chat")
    payload = _to_openai_dict(result)
    _repair_completion_payload(payload, provider, litellm_model)
    _log_completion_shape(payload, provider, litellm_model)
    return payload


class _StreamTally:
    """Running totals for one streamed completion. Metadata only, no content."""

    def __init__(self) -> None:
        self.chunks = 0
        self.content_chars = 0
        self.tool_calls = 0
        self.repaired_tool_calls = 0
        self.finish_reason: str | None = None
        self.error: str | None = None

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


class _ToolCallBuffer:
    """Reassembles streamed tool calls so their `arguments` can be repaired.

    A tool call arrives spread over many deltas: the opening one carries `id`
    and `name`, the rest carry `arguments` fragments the client concatenates.
    Whether those fragments concatenate into a usable object is only knowable
    once they are all in hand — the first fragment of a double-encoded payload
    (`'"{\\'`) is indistinguishable from a slow provider. So tool-call deltas are
    held here, joined, normalised, and emitted as one complete tool-call delta
    just before the finishing chunk. Content deltas are never buffered, so token
    streaming is untouched.
    """

    def __init__(self) -> None:
        self._calls: dict[tuple[int, int], dict[str, Any]] = {}
        self._order: list[tuple[int, int]] = []

    def __bool__(self) -> bool:
        return bool(self._order)

    def absorb(self, choice_index: int, tool_calls: Any) -> None:
        for position, raw in enumerate(tool_calls or []):
            if not isinstance(raw, dict):
                continue
            index = raw.get("index")
            if not isinstance(index, int):
                index = position
            key = (choice_index, index)
            call = self._calls.get(key)
            if call is None:
                call = {
                    "index": index,
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                }
                self._calls[key] = call
                self._order.append(key)
            if raw.get("id"):
                call["id"] = raw["id"]
            if raw.get("type"):
                call["type"] = raw["type"]
            function = raw.get("function")
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            # Providers split at different granularities: some send the whole
            # name once, some fragment it. Appending handles fragments; skipping
            # an exact repeat handles providers that resend the full name.
            if isinstance(name, str) and name and name != call["function"]["name"]:
                call["function"]["name"] += name
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                call["function"]["arguments"] += arguments

    def drain(self, provider: str, model: str) -> tuple[dict[int, list[dict[str, Any]]], int]:
        """Take everything buffered, grouped by choice index, arguments repaired."""
        grouped: dict[int, list[dict[str, Any]]] = {}
        repaired = 0
        for choice_index, _ in self._order:
            grouped.setdefault(choice_index, [])
        for key in self._order:
            grouped[key[0]].append(self._calls[key])
        for calls in grouped.values():
            calls.sort(key=lambda call: call.get("index", 0))
            repaired += _repair_tool_calls(calls, provider, model)
        self._calls.clear()
        self._order.clear()
        return grouped, repaired


def _tool_call_chunks(
    template: Mapping[str, Any], grouped: Mapping[int, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """One chunk per choice carrying that choice's complete tool calls."""
    return [
        {
            "id": template.get("id"),
            "object": template.get("object") or "chat.completion.chunk",
            "created": template.get("created"),
            "model": template.get("model"),
            "choices": [
                {
                    "index": choice_index,
                    "delta": {"role": "assistant", "tool_calls": calls},
                    "finish_reason": None,
                }
            ],
        }
        for choice_index, calls in grouped.items()
        if calls
    ]


def _chunk_carries_nothing(chunk: Mapping[str, Any]) -> bool:
    """True when a chunk has no payload left after its tool calls were held back."""
    if chunk.get("usage"):
        return False
    choices = chunk.get("choices") or []
    if not choices:
        return False
    for choice in choices:
        if not isinstance(choice, dict):
            return False
        if choice.get("finish_reason"):
            return False
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            return False
        if any(value not in (None, "", [], {}) for value in delta.values()):
            return False
    return True


def _empty_stream_message(provider: str, model: str, finish_reason: str | None) -> str:
    """Client text for a completion that succeeded and said nothing."""
    return (
        f"{_call_label(provider, model)} accepted the request but returned no content and no "
        f"tool calls (finish_reason: {finish_reason or 'none'}). Check that the model supports "
        "the capabilities this request needs, or select a different model."
    )


def _error_frame(message: str, provider: str, model: str) -> str:
    """SSE frame an OpenAI client turns back into a raised APIError."""
    return (
        "data: "
        + json.dumps(
            {
                "error": {
                    "message": message,
                    "type": "api_error",
                    "code": "upstream_error",
                    "provider": provider,
                    "model": model,
                }
            }
        )
        + "\n\n"
    )


async def _aiter_stream(stream: Any):
    if hasattr(stream, "__aiter__"):
        async for chunk in stream:
            yield chunk
    else:
        for chunk in stream:
            yield chunk


async def _stream_sse(
    stream: Any,
    provider: str = "",
    model: str = "",
    credentials: Mapping[str, Any] | None = None,
) -> AsyncIterator[str]:
    tally = _StreamTally()
    buffer = _ToolCallBuffer()
    template: dict[str, Any] = {}
    try:
        async for chunk in _aiter_stream(stream):
            payload = _chunk_payload(chunk)
            try:
                data = json.loads(payload)
            except ValueError:
                tally.observe(payload)
                yield f"data: {payload}\n\n"
                continue
            if not isinstance(data, dict):
                tally.observe(payload)
                yield f"data: {payload}\n\n"
                continue
            template = data

            held = False
            finishing = False
            for choice in data.get("choices") or []:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta")
                if isinstance(delta, dict) and delta.get("tool_calls"):
                    index = choice.get("index")
                    buffer.absorb(index if isinstance(index, int) else 0, delta["tool_calls"])
                    delta["tool_calls"] = None
                    held = True
                if choice.get("finish_reason"):
                    finishing = True

            if finishing and buffer:
                grouped, repaired = buffer.drain(provider, model)
                tally.repaired_tool_calls += repaired
                for flushed in _tool_call_chunks(template, grouped):
                    out = json.dumps(flushed)
                    tally.observe(out)
                    yield f"data: {out}\n\n"

            if held:
                if _chunk_carries_nothing(data):
                    continue
                payload = json.dumps(data)
            tally.observe(payload)
            yield f"data: {payload}\n\n"

        # A provider that ends without a finish_reason still owes us its calls.
        if buffer:
            grouped, repaired = buffer.drain(provider, model)
            tally.repaired_tool_calls += repaired
            for flushed in _tool_call_chunks(template, grouped):
                out = json.dumps(flushed)
                tally.observe(out)
                yield f"data: {out}\n\n"

        # A 200 that carries nothing is indistinguishable from a dead connection
        # by the time it reaches the UI, which can only say "the server didn't
        # return a response". Name the call and its finish_reason instead, so
        # the next person has something to search for.
        if tally.content_chars == 0 and tally.tool_calls == 0:
            tally.error = "empty completion"
            provider_error_log.record_failure(
                provider, "chat", _empty_stream_message(provider, model, tally.finish_reason)
            )
            logger.warning(
                "LLM chat stream produced no content and no tool calls",
                provider=provider,
                model=model,
                finish_reason=tally.finish_reason,
                chunks=tally.chunks,
            )
            yield _error_frame(
                _empty_stream_message(provider, model, tally.finish_reason), provider, model
            )
        else:
            # Content actually reached the client, so whatever the banner was
            # holding against this provider is no longer true.
            provider_error_log.record_success(provider, "chat")
    except Exception as exc:
        # Mid-stream failures used to surface as a truncated stream, which the
        # UI could only report as "the server didn't return a response". Emit an
        # OpenAI error frame instead: the client raises it with the provider's
        # own wording, so the cause reaches the chat and the logs alike.
        detail = _redact(f"{type(exc).__name__}: {exc}", credentials or {})
        tally.error = detail
        logger.error("LLM chat stream failed", provider=provider, model=model, error=detail)
        message = _upstream_client_message(detail, provider, model, exc)
        provider_error_log.record_failure(provider, "chat", message)
        yield _error_frame(message, provider, model)
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
        if tally.error:
            return  # already logged with its cause by the stream's error handler
        empty = tally.content_chars == 0 and tally.tool_calls == 0
        log = logger.warning if empty else logger.info
        log(
            "LLM chat stream produced no content and no tool calls" if empty else "LLM chat stream",
            provider=provider,
            model=model,
            finish_reason=tally.finish_reason,
            content_chars=tally.content_chars,
            tool_calls=tally.tool_calls,
            repaired_tool_calls=tally.repaired_tool_calls,
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
        logger.error("LLM embeddings failed", provider=provider, model=litellm_model, error=detail)
        message = _upstream_client_message(detail, provider, litellm_model, exc)
        provider_error_log.record_failure(provider, "embedding", message)
        raise LlmGatewayError(
            message,
            _upstream_status_code(exc),
            detail=detail,
        ) from exc
    provider_error_log.record_success(provider, "embedding")
    return _to_openai_dict(result)
