"""LLM gateway: route OpenAI-shaped requests through LiteLLM using OpenRAG config."""

import json
from types import SimpleNamespace

import pytest

from config.config_manager import (
    AnthropicConfig,
    GenericProviderConfig,
    OllamaConfig,
    OpenAIConfig,
    ProvidersConfig,
    WatsonXConfig,
)
from services.llm_gateway import (
    LlmGatewayError,
    chat_completions,
    embeddings,
    provider_credentials,
    resolve_call,
    split_model_id,
)


def _config(**overrides):
    providers = SimpleNamespace(
        openai=SimpleNamespace(api_key="sk-openai", configured=True),
        anthropic=SimpleNamespace(api_key="sk-ant", configured=True),
        ollama=SimpleNamespace(
            endpoint="http://localhost:11434", resolved_endpoint="", configured=True
        ),
        watsonx=SimpleNamespace(
            api_key="wx-key",
            endpoint="https://us-south.ml.cloud.ibm.com",
            project_id="proj",
            configured=True,
        ),
    )
    agent = SimpleNamespace(llm_model="gpt-4o-mini", llm_provider="openai")
    knowledge = SimpleNamespace(
        embedding_model="text-embedding-3-small", embedding_provider="openai"
    )
    cfg = SimpleNamespace(providers=providers, agent=agent, knowledge=knowledge)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_split_model_id_recognises_known_prefixes():
    assert split_model_id("anthropic/claude-sonnet-4-5") == ("anthropic", "claude-sonnet-4-5")
    assert split_model_id("gpt-4o-mini") == (None, "gpt-4o-mini")
    assert split_model_id("openai/gpt-4o") == ("openai", "gpt-4o")


def test_resolve_call_uses_configured_provider_when_model_is_bare():
    model, provider, creds = resolve_call("gpt-4o-mini", kind="chat", config=_config())
    assert provider == "openai"
    assert model == "gpt-4o-mini"
    assert creds["api_key"] == "sk-openai"


def test_resolve_call_anthropic_gets_litellm_prefix():
    cfg = _config(agent=SimpleNamespace(llm_model="claude-sonnet-4-5", llm_provider="anthropic"))
    model, provider, creds = resolve_call(None, kind="chat", config=cfg)
    assert provider == "anthropic"
    assert model == "anthropic/claude-sonnet-4-5"
    assert creds["api_key"] == "sk-ant"


def test_resolve_call_watsonx_includes_project_and_endpoint():
    cfg = _config(
        knowledge=SimpleNamespace(embedding_model="ibm/slate", embedding_provider="watsonx")
    )
    model, provider, creds = resolve_call("ibm/slate", kind="embedding", config=cfg)
    assert provider == "watsonx"
    assert model == "watsonx/ibm/slate"
    assert creds["project_id"] == "proj"
    assert creds["api_base"] == "https://us-south.ml.cloud.ibm.com"


def test_legacy_text_embedding_3_small_routes_to_openai_not_selected_provider():
    cfg = _config(
        knowledge=SimpleNamespace(
            embedding_model="azure-deployment",
            embedding_provider="azure",
            legacy_embedding_provider_map={},
        )
    )

    model, provider, creds = resolve_call(
        "legacy:text-embedding-3-small", kind="embedding", config=cfg
    )

    assert provider == "openai"
    assert model == "text-embedding-3-small"
    assert creds["api_key"] == "sk-openai"


def test_operator_mapping_routes_other_legacy_embedding_models():
    cfg = _config()
    cfg.knowledge.legacy_embedding_provider_map = {"ibm/slate-125m": "watsonx"}

    model, provider, creds = resolve_call("legacy:ibm/slate-125m", kind="embedding", config=cfg)

    assert provider == "watsonx"
    assert model == "watsonx/ibm/slate-125m"
    assert creds["project_id"] == "proj"


def test_unmapped_legacy_model_does_not_fall_back_to_selected_provider():
    cfg = _config(
        knowledge=SimpleNamespace(
            embedding_model="azure-deployment",
            embedding_provider="azure",
            legacy_embedding_provider_map={},
        )
    )

    with pytest.raises(LlmGatewayError) as exc:
        resolve_call("legacy:ibm/slate-125m", kind="embedding", config=cfg)

    assert "has no provider mapping" in exc.value.message
    assert "legacy_embedding_provider_map" in exc.value.message


def test_indexed_space_with_removed_provider_does_not_fall_back_to_selected_provider():
    cfg = _config()

    with pytest.raises(LlmGatewayError) as exc:
        resolve_call("space:removed:model-a", kind="embedding", config=cfg)

    assert "removed" in exc.value.message
    assert "not configured" in exc.value.message


def test_provider_credentials_rejects_unknown_provider():
    with pytest.raises(LlmGatewayError) as exc:
        provider_credentials("gemini", _config())
    assert exc.value.status_code == 400
    assert "gemini" in exc.value.message


def test_provider_credentials_rejects_missing_openai_key():
    cfg = _config()
    cfg.providers.openai.api_key = ""
    with pytest.raises(LlmGatewayError) as exc:
        provider_credentials("openai", cfg)
    assert "not configured" in exc.value.message


def test_provider_credentials_supports_arbitrary_litellm_provider():
    providers = ProvidersConfig(
        openai=OpenAIConfig(),
        anthropic=AnthropicConfig(),
        watsonx=WatsonXConfig(),
        ollama=OllamaConfig(),
        custom={
            "gemini": GenericProviderConfig(
                credentials={
                    "api_key": "gemini-secret",
                    "vertex_project": "project-1",
                },
                configured=True,
            )
        },
    )
    cfg = SimpleNamespace(providers=providers)

    assert provider_credentials("gemini", cfg) == {
        "api_key": "gemini-secret",
        "vertex_project": "project-1",
    }


def test_indexed_space_routes_through_its_configured_generic_provider():
    providers = ProvidersConfig(
        openai=OpenAIConfig(),
        anthropic=AnthropicConfig(),
        watsonx=WatsonXConfig(),
        ollama=OllamaConfig(),
        custom={
            "gemini": GenericProviderConfig(
                credentials={"api_key": "gemini-secret"},
                configured=True,
            )
        },
    )
    cfg = SimpleNamespace(providers=providers)

    model, provider, credentials = resolve_call(
        "space:gemini:text-embedding-004", kind="embedding", config=cfg
    )

    assert model == "gemini/text-embedding-004"
    assert provider == "gemini"
    assert credentials == {"api_key": "gemini-secret"}


@pytest.mark.asyncio
async def test_chat_completions_calls_litellm_with_config_key(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
        }

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)

    result = await chat_completions(
        {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        config=_config(),
    )
    assert result["choices"][0]["message"]["content"] == "hi"
    assert captured["model"] == "gpt-4o-mini"
    assert captured["api_key"] == "sk-openai"
    assert captured["messages"][0]["content"] == "hi"


@pytest.mark.asyncio
async def test_chat_completions_forwards_tools(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return {"id": "chatcmpl-1", "choices": []}

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    tools = [{"type": "function", "function": {"name": "search"}}]
    await chat_completions(
        {
            "model": "anthropic/claude-sonnet-4-5",
            "messages": [],
            "tools": tools,
            "tool_choice": "auto",
        },
        config=_config(),
    )
    assert captured["tools"] == tools
    assert captured["tool_choice"] == "auto"
    assert captured["model"] == "anthropic/claude-sonnet-4-5"
    assert captured["api_key"] == "sk-ant"


@pytest.mark.asyncio
async def test_chat_completions_stream_emits_sse(monkeypatch):
    class _Chunk:
        def model_dump_json(self):
            return '{"choices":[{"delta":{"content":"hi"}}]}'

    async def fake_stream():
        yield _Chunk()

    async def fake_acompletion(**kwargs):
        assert kwargs["stream"] is True
        return fake_stream()

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    stream = await chat_completions(
        {"model": "gpt-4o-mini", "messages": [], "stream": True},
        config=_config(),
    )
    lines = [line async for line in stream]
    assert lines[0].startswith("data: {")
    assert lines[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_chat_completions_redacts_api_key_on_failure(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("upstream rejected sk-openai")

    monkeypatch.setattr("litellm.acompletion", boom)
    with pytest.raises(LlmGatewayError) as exc:
        await chat_completions({"model": "gpt-4o-mini", "messages": []}, config=_config())
    assert exc.value.status_code == 502
    # The key never appears anywhere, and the log-only detail keeps the marker.
    assert "sk-openai" not in exc.value.message
    assert "sk-openai" not in exc.value.detail
    assert "[redacted]" in exc.value.detail


@pytest.mark.asyncio
async def test_chat_completions_keeps_upstream_internals_out_of_client_message(monkeypatch):
    """CodeQL py/stack-trace-exposure: upstream exception text is log-only."""

    async def boom(**kwargs):
        raise RuntimeError("Traceback /srv/app/litellm/router.py line 42: connect to 10.0.0.5")

    monkeypatch.setattr("litellm.acompletion", boom)
    with pytest.raises(LlmGatewayError) as exc:
        await chat_completions({"model": "gpt-4o-mini", "messages": []}, config=_config())

    assert exc.value.status_code == 502
    # A RuntimeError from our own code is not the provider's to explain, so the
    # message collapses to the fixed literal — only the failing call is named.
    assert exc.value.message.startswith(
        "The model provider could not be reached. Please try again."
    )
    assert "openai/gpt-4o-mini" in exc.value.message
    for leak in ("RuntimeError", "Traceback", "/srv/app", "10.0.0.5"):
        assert leak not in exc.value.message
    # Operators still get the full picture in logs.
    assert "RuntimeError" in exc.value.detail
    assert "10.0.0.5" in exc.value.detail


@pytest.mark.asyncio
async def test_chat_completions_keeps_credential_errors_actionable(monkeypatch):
    """A bad key must stay diagnosable in onboarding, not collapse to the generic text."""

    async def boom(**kwargs):
        raise RuntimeError("Incorrect API key provided")

    monkeypatch.setattr("litellm.acompletion", boom)
    with pytest.raises(LlmGatewayError) as exc:
        await chat_completions({"model": "gpt-4o-mini", "messages": []}, config=_config())

    assert exc.value.status_code == 502
    assert "api key" in exc.value.message.lower()
    # Classified, not forwarded: the client message is a fixed literal.
    assert "Incorrect API key provided" not in exc.value.message
    assert "Incorrect API key provided" in exc.value.detail


@pytest.mark.asyncio
async def test_embeddings_keeps_upstream_internals_out_of_client_message(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("Traceback /srv/app/litellm/router.py: connect to 10.0.0.5")

    monkeypatch.setattr("litellm.aembedding", boom)
    with pytest.raises(LlmGatewayError) as exc:
        await embeddings({"model": "text-embedding-3-small", "input": ["hi"]}, config=_config())

    assert exc.value.status_code == 502
    assert exc.value.message.startswith(
        "The model provider could not be reached. Please try again."
    )
    for leak in ("RuntimeError", "Traceback", "/srv/app", "10.0.0.5"):
        assert leak not in exc.value.message
    assert "10.0.0.5" in exc.value.detail


def test_gateway_error_detail_defaults_to_message():
    """Authored 4xx messages are already safe, so detail mirrors them."""
    exc = LlmGatewayError("model is required", 400)
    assert exc.detail == exc.message


@pytest.mark.asyncio
async def test_embeddings_calls_litellm(monkeypatch):
    captured = {}

    async def fake_aembedding(**kwargs):
        captured.update(kwargs)
        return {"object": "list", "data": [{"embedding": [0.1], "index": 0}]}

    monkeypatch.setattr("litellm.aembedding", fake_aembedding)
    result = await embeddings(
        {"model": "text-embedding-3-small", "input": ["hello"]},
        config=_config(),
    )
    assert result["data"][0]["embedding"] == [0.1]
    assert captured["api_key"] == "sk-openai"
    assert captured["input"] == ["hello"]


class _RecordingLogger:
    """structlog-style logger that records calls instead of emitting them."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    def _record(self, level):
        def log(event, **kwargs):
            self.calls.append((level, event, kwargs))

        return log

    def __getattr__(self, name):
        return self._record(name)


def test_log_completion_shape_flags_an_empty_completion(monkeypatch):
    """An empty completion must be visible in logs, not silently returned.

    Langflow's agent ends its loop on an empty completion and the user just
    sees "The server didn't return a response", with nothing upstream to
    explain it.
    """
    from services import llm_gateway

    recorder = _RecordingLogger()
    monkeypatch.setattr(llm_gateway, "logger", recorder)

    payload = {"choices": [{"finish_reason": "stop", "message": {"content": "", "tool_calls": []}}]}
    llm_gateway._log_completion_shape(payload, "watsonx", "watsonx/ibm/granite-4-h-small")

    assert recorder.calls, "nothing was logged"
    level, event, fields = recorder.calls[0]
    assert level == "warning"
    assert "no content and no tool calls" in event
    assert fields["provider"] == "watsonx"
    assert fields["tool_calls"] == 0
    assert fields["content_chars"] == 0


def test_log_completion_shape_reports_a_normal_completion(monkeypatch):
    from services import llm_gateway

    recorder = _RecordingLogger()
    monkeypatch.setattr(llm_gateway, "logger", recorder)

    payload = {
        "choices": [
            {"finish_reason": "stop", "message": {"content": "secret answer", "tool_calls": []}}
        ]
    }
    llm_gateway._log_completion_shape(payload, "openai", "gpt-4o-mini")

    level, _event, fields = recorder.calls[0]
    assert level == "info"
    assert fields["content_chars"] == len("secret answer")
    # Metadata only — message content must never reach the logs.
    assert "secret answer" not in str(recorder.calls)


def test_log_completion_shape_survives_an_unexpected_payload():
    from services import llm_gateway

    # Must never raise: diagnostics run on the response path.
    llm_gateway._log_completion_shape({"choices": "not-a-list"}, "openai", "gpt-4o-mini")
    llm_gateway._log_completion_shape({}, "openai", "gpt-4o-mini")


@pytest.mark.asyncio
async def test_stream_sse_still_forwards_every_chunk_and_terminates():
    """Diagnostics must not disturb the stream itself."""
    from services import llm_gateway

    chunks = [
        {"choices": [{"delta": {"content": "he"}}]},
        {"choices": [{"delta": {"content": "llo"}, "finish_reason": "stop"}]},
    ]

    async def gen():
        for chunk in chunks:
            yield chunk

    out = [line async for line in llm_gateway._stream_sse(gen(), "openai", "gpt-4o-mini")]

    assert out[-1] == "data: [DONE]\n\n"
    assert len(out) == len(chunks) + 1
    assert '"content": "he"' in out[0] or '"content":"he"' in out[0]


@pytest.mark.asyncio
async def test_stream_sse_warns_when_a_stream_yields_nothing_usable(monkeypatch):
    """The watsonx symptom: 200 OK, chunks arrive, but no content and no tool calls."""
    from services import llm_gateway

    recorder = _RecordingLogger()
    monkeypatch.setattr(llm_gateway, "logger", recorder)

    async def gen():
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}

    [
        line
        async for line in llm_gateway._stream_sse(gen(), "watsonx", "watsonx/ibm/granite-4-h-small")
    ]

    levels = [call[0] for call in recorder.calls]
    assert "warning" in levels
    _level, event, fields = next(c for c in recorder.calls if c[0] == "warning")
    assert "no content and no tool calls" in event
    assert fields["provider"] == "watsonx"
    assert fields["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_stream_sse_counts_tool_calls_as_usable_output(monkeypatch):
    from services import llm_gateway

    recorder = _RecordingLogger()
    monkeypatch.setattr(llm_gateway, "logger", recorder)

    async def gen():
        yield {
            "choices": [{"delta": {"tool_calls": [{"index": 0}]}, "finish_reason": "tool_calls"}]
        }

    [line async for line in llm_gateway._stream_sse(gen(), "openai", "gpt-4o-mini")]

    level, event, fields = recorder.calls[0]
    assert level == "info"
    assert fields["tool_calls"] == 1


@pytest.mark.asyncio
async def test_chat_completions_lets_litellm_drop_provider_unsupported_params(monkeypatch):
    """A multi-provider proxy must degrade, not 502, on provider param gaps.

    OpenAI-compatible clients send OpenAI's full parameter set, but watsonx
    rejects `parallel_tool_calls`, `max_completion_tokens` and `logit_bias`,
    and LiteLLM raises UnsupportedParamsError rather than ignoring them.
    """
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return {"id": "1", "choices": [{"message": {"role": "assistant", "content": "hi"}}]}

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)

    await chat_completions(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "parallel_tool_calls": True,
            "max_completion_tokens": 64,
        },
        config=_config(),
    )

    assert captured["drop_params"] is True
    # The params are still forwarded — LiteLLM decides per provider what to keep.
    assert captured["parallel_tool_calls"] is True
    assert captured["max_completion_tokens"] == 64


def test_watsonx_rejects_params_we_forward_unless_they_are_dropped():
    """Pin the upstream behaviour this fix relies on.

    If LiteLLM ever starts accepting these for watsonx, `drop_params` becomes
    redundant rather than wrong — but while it rejects them, forwarding them
    without the flag is a hard failure for every watsonx caller.
    """
    from litellm.exceptions import UnsupportedParamsError
    from litellm.utils import get_optional_params

    for param, value in (
        ("parallel_tool_calls", True),
        ("max_completion_tokens", 64),
        ("logit_bias", {"1": 1}),
    ):
        with pytest.raises(UnsupportedParamsError):
            get_optional_params(
                model="ibm/granite-4-h-small",
                custom_llm_provider="watsonx",
                **{param: value},
            )

        dropped = get_optional_params(
            model="ibm/granite-4-h-small",
            custom_llm_provider="watsonx",
            drop_params=True,
            **{param: value},
        )
        assert param not in dropped


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        # Canonical tag. The name keeps its own slashes and colons.
        ("watsonx:openai/gpt-oss-120b", ("watsonx", "openai/gpt-oss-120b")),
        ("watsonx:ibm/granite-4-h-small", ("watsonx", "ibm/granite-4-h-small")),
        ("ollama:gpt-oss:120b-cloud", ("ollama", "gpt-oss:120b-cloud")),
        ("openai:ft:gpt-4-0613", ("openai", "ft:gpt-4-0613")),
        # Legacy `provider/model` tags still resolve.
        ("watsonx/ibm/granite-4-h-small", ("watsonx", "ibm/granite-4-h-small")),
        ("anthropic/claude-sonnet-4-5", ("anthropic", "claude-sonnet-4-5")),
        # Untagged ids are left to the configured default provider.
        ("gpt-4o-mini", (None, "gpt-4o-mini")),
        ("gpt-oss:120b-cloud", (None, "gpt-oss:120b-cloud")),
        ("ft:gpt-4-0613", (None, "ft:gpt-4-0613")),
    ],
)
def test_split_model_id_handles_tagged_and_untagged_ids(model_id, expected):
    from services.llm_gateway import split_model_id

    assert split_model_id(model_id) == expected


def test_a_vendor_qualified_name_is_not_mistaken_for_a_provider_tag():
    """watsonx serves `openai/gpt-oss-120b`; the `openai/` is part of the name.

    Splitting on the slash routed it to OpenAI as a bare `gpt-oss-120b`, which
    LiteLLM rejects with "LLM Provider NOT provided", surfacing to the user as
    "The model provider could not be reached."
    """
    from services.llm_gateway import split_model_id

    assert split_model_id("openai/gpt-oss-120b") == ("watsonx", "openai/gpt-oss-120b")


def test_model_ids_served_by_v1_models_round_trip():
    """Every id `/v1/models` publishes must resolve back to its owner."""
    from services.llm_gateway import split_model_id
    from services.model_catalog import openai_models_list

    for row in openai_models_list()["data"]:
        provider, _name = split_model_id(row["id"])
        if row["owned_by"] == "openai":
            continue
        assert provider == row["owned_by"], row


def test_no_catalogue_id_has_a_provider_shaped_prefix_before_a_colon():
    """The property that makes `:` a safe separator.

    If a future model id breaks this, `provider:model` becomes ambiguous the
    same way `provider/model` already is.
    """
    from services.model_catalog import PROVIDER_SEPARATOR_SAFE_CHECK

    ambiguous = PROVIDER_SEPARATOR_SAFE_CHECK()
    assert ambiguous == [], f"colon-ambiguous catalogue ids: {ambiguous}"


# --------------------------------------------------------------------------
# Tool-call arguments that arrive serialised twice
# --------------------------------------------------------------------------

#: What `watsonx/ibm/granite-4-h-small` actually sends: the arguments object,
#: serialised, then serialised again. Captured from a live call.
_DOUBLE_ENCODED_ARGUMENTS = '"{\\n  \\"query\\": \\"Earned Leaves\\"\\n}"'
_WELL_FORMED_ARGUMENTS = '{"query": "Earned Leaves"}'


def test_normalise_tool_arguments_unwraps_a_double_encoded_payload():
    from services.llm_gateway import _normalise_tool_arguments

    arguments, repaired = _normalise_tool_arguments(_DOUBLE_ENCODED_ARGUMENTS)

    assert repaired is True
    assert json.loads(arguments) == {"query": "Earned Leaves"}


def test_normalise_tool_arguments_leaves_well_formed_payloads_untouched():
    from services.llm_gateway import _normalise_tool_arguments

    for payload in (_WELL_FORMED_ARGUMENTS, "{}", '   {"a": 1}', "not json", "", None):
        assert _normalise_tool_arguments(payload) == (payload, False)


def test_normalise_tool_arguments_serialises_a_mapping():
    """Some providers send the object itself; OpenAI clients parse a string."""
    from services.llm_gateway import _normalise_tool_arguments

    arguments, repaired = _normalise_tool_arguments({"query": "x"})
    assert repaired is True
    assert json.loads(arguments) == {"query": "x"}


def test_normalise_tool_arguments_refuses_a_quoted_scalar():
    """`"hello"` is a string, not an arguments object — leave it for the client."""
    from services.llm_gateway import _normalise_tool_arguments

    assert _normalise_tool_arguments('"hello"') == ('"hello"', False)


@pytest.mark.asyncio
async def test_chat_completions_repairs_double_encoded_tool_arguments(monkeypatch):
    """Non-streaming: the client must receive arguments it can parse into a mapping."""

    async def fake(**kwargs):
        return {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "search_documents",
                                    "arguments": _DOUBLE_ENCODED_ARGUMENTS,
                                },
                            }
                        ],
                    },
                }
            ]
        }

    monkeypatch.setattr("litellm.acompletion", fake)
    payload = await chat_completions(
        {"model": "watsonx:ibm/granite-4-h-small", "messages": []}, config=_config()
    )

    arguments = payload["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(arguments) == {"query": "Earned Leaves"}


def _tool_call_deltas(fragments, name="search_documents", call_id="call_1"):
    """One chunk per fragment, the way a provider streams a tool call."""
    chunks = [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "index": 0,
                                "function": {"name": name, "arguments": ""},
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ]
        }
    ]
    for fragment in fragments:
        chunks.append(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": None,
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": None,
                                    "type": "function",
                                    "index": 0,
                                    "function": {"name": "", "arguments": fragment},
                                }
                            ],
                        },
                        "finish_reason": None,
                    }
                ]
            }
        )
    chunks.append(
        {"choices": [{"index": 0, "delta": {"content": None}, "finish_reason": "tool_calls"}]}
    )
    return chunks


def _streamed_tool_calls(lines):
    """Every tool call the gateway put on the wire, in order."""
    calls = []
    for line in lines:
        if not line.startswith("data: ") or line.startswith("data: [DONE]"):
            continue
        for choice in json.loads(line[len("data: ") :]).get("choices") or []:
            calls.extend((choice.get("delta") or {}).get("tool_calls") or [])
    return calls


@pytest.mark.asyncio
async def test_stream_sse_reassembles_and_repairs_fragmented_tool_arguments():
    """The granite-4 symptom: fragments only reveal the double encoding once joined."""
    from services import llm_gateway

    # Exactly how the model splits it on the wire.
    fragments = [
        '"{\\',
        "n",
        " ",
        ' \\"',
        "query",
        '\\":',
        ' \\"',
        "Earned Leaves",
        '\\"\\',
        "n",
        '}"',
    ]

    async def gen():
        for chunk in _tool_call_deltas(fragments):
            yield chunk

    lines = [
        line
        async for line in llm_gateway._stream_sse(gen(), "watsonx", "watsonx/ibm/granite-4-h-small")
    ]

    calls = _streamed_tool_calls(lines)
    assert len(calls) == 1, "fragments must be emitted as one complete tool call"
    assert calls[0]["id"] == "call_1"
    assert calls[0]["function"]["name"] == "search_documents"
    assert json.loads(calls[0]["function"]["arguments"]) == {"query": "Earned Leaves"}
    assert lines[-1] == "data: [DONE]\n\n"
    # The finishing chunk still arrives, and after the tool call.
    assert '"finish_reason": "tool_calls"' in lines[-2]


@pytest.mark.asyncio
async def test_stream_sse_leaves_a_well_formed_tool_call_intact():
    """Reassembly must be lossless for providers that already behave."""
    from services import llm_gateway

    fragments = ['{"', "query", '": "', "Earned Leaves", '"}']

    async def gen():
        for chunk in _tool_call_deltas(fragments):
            yield chunk

    lines = [line async for line in llm_gateway._stream_sse(gen(), "openai", "gpt-4o-mini")]

    calls = _streamed_tool_calls(lines)
    assert len(calls) == 1
    assert json.loads(calls[0]["function"]["arguments"]) == {"query": "Earned Leaves"}


@pytest.mark.asyncio
async def test_stream_sse_keeps_content_flowing_while_tool_calls_are_held():
    """Buffering tool calls must not delay or drop streamed text."""
    from services import llm_gateway

    async def gen():
        yield {"choices": [{"index": 0, "delta": {"content": "th"}}]}
        yield {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": "inking",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "index": 0,
                                "type": "function",
                                "function": {"name": "t", "arguments": "{}"},
                            }
                        ],
                    },
                }
            ]
        }
        yield {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}

    lines = [line async for line in llm_gateway._stream_sse(gen(), "openai", "gpt-4o-mini")]

    text = "".join(
        (choice.get("delta") or {}).get("content") or ""
        for line in lines
        if line.startswith("data: ") and not line.startswith("data: [DONE]")
        for choice in json.loads(line[len("data: ") :]).get("choices") or []
    )
    assert text == "thinking"
    assert len(_streamed_tool_calls(lines)) == 1


@pytest.mark.asyncio
async def test_stream_sse_flushes_tool_calls_when_the_provider_sends_no_finish_reason():
    from services import llm_gateway

    async def gen():
        yield {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "index": 0,
                                "type": "function",
                                "function": {
                                    "name": "search_documents",
                                    "arguments": _DOUBLE_ENCODED_ARGUMENTS,
                                },
                            }
                        ]
                    },
                }
            ]
        }

    lines = [
        line
        async for line in llm_gateway._stream_sse(gen(), "watsonx", "watsonx/ibm/granite-4-h-small")
    ]

    calls = _streamed_tool_calls(lines)
    assert len(calls) == 1
    assert json.loads(calls[0]["function"]["arguments"]) == {"query": "Earned Leaves"}


@pytest.mark.asyncio
async def test_stream_sse_logs_the_repair(monkeypatch):
    from services import llm_gateway

    recorder = _RecordingLogger()
    monkeypatch.setattr(llm_gateway, "logger", recorder)

    async def gen():
        for chunk in _tool_call_deltas(['"{\\', 'n \\"query\\": \\"x\\"\\', 'n}"']):
            yield chunk

    [
        line
        async for line in llm_gateway._stream_sse(gen(), "watsonx", "watsonx/ibm/granite-4-h-small")
    ]

    warnings = [call for call in recorder.calls if call[0] == "warning"]
    assert any("Repaired double-encoded tool call arguments" in call[1] for call in warnings)
    _level, _event, fields = next(call for call in warnings if "Repaired" in call[1])
    assert fields["model"] == "watsonx/ibm/granite-4-h-small"
    assert fields["tool_calls"] == 1


# --------------------------------------------------------------------------
# Surfacing the real upstream failure
# --------------------------------------------------------------------------


class _FakeLiteLLMError(Exception):
    """Stands in for a LiteLLM exception: tagged with the provider it called."""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.llm_provider = "watsonx"
        self.status_code = status_code


@pytest.mark.asyncio
async def test_chat_completions_surfaces_the_provider_error_body(monkeypatch):
    """An operator must be able to read what the provider actually objected to."""

    async def boom(**kwargs):
        raise _FakeLiteLLMError(
            'OpenAILikeError: {"errors":[{"code":"model_not_supported","message":'
            "\"Model 'ibm/granite-3-3-8b-instruct' was not found. This model may be "
            'unsupported, deprecated, or removed."}],"status_code":404}'
        )

    monkeypatch.setattr("litellm.acompletion", boom)
    with pytest.raises(LlmGatewayError) as exc:
        await chat_completions(
            {"model": "watsonx:ibm/granite-3-3-8b-instruct", "messages": []}, config=_config()
        )

    assert "watsonx/ibm/granite-3-3-8b-instruct" in exc.value.message
    assert "was not found" in exc.value.message
    assert "OpenAILikeError" not in exc.value.message


@pytest.mark.asyncio
async def test_chat_completions_surfaces_a_litellm_exception_without_a_json_body(monkeypatch):
    async def boom(**kwargs):
        raise _FakeLiteLLMError("BadRequestError: tool_choice is not supported for this model")

    monkeypatch.setattr("litellm.acompletion", boom)
    with pytest.raises(LlmGatewayError) as exc:
        await chat_completions({"model": "gpt-4o-mini", "messages": []}, config=_config())

    assert "tool_choice is not supported" in exc.value.message


@pytest.mark.asyncio
async def test_chat_completions_passes_through_a_rate_limit_status(monkeypatch):
    async def boom(**kwargs):
        raise _FakeLiteLLMError("rate limit exceeded, retry in 30s", status_code=429)

    monkeypatch.setattr("litellm.acompletion", boom)
    with pytest.raises(LlmGatewayError) as exc:
        await chat_completions({"model": "gpt-4o-mini", "messages": []}, config=_config())

    assert exc.value.status_code == 429
    assert "rate limit exceeded" in exc.value.message


@pytest.mark.asyncio
async def test_chat_completions_masks_an_upstream_4xx_as_a_gateway_failure(monkeypatch):
    """An upstream 401 must not read to the client as an OpenRAG auth failure."""

    async def boom(**kwargs):
        raise _FakeLiteLLMError("model does not exist", status_code=404)

    monkeypatch.setattr("litellm.acompletion", boom)
    with pytest.raises(LlmGatewayError) as exc:
        await chat_completions({"model": "gpt-4o-mini", "messages": []}, config=_config())

    assert exc.value.status_code == 502


def test_sanitise_upstream_detail_drops_interpreter_state():
    from services.llm_gateway import _sanitise_upstream_detail

    text = _sanitise_upstream_detail(
        "ConnectError: connect to 10.0.0.5 failed\n"
        'Traceback (most recent call last):\n  File "/srv/app/litellm/router.py", line 42'
    )
    for leak in ("Traceback", "/srv/app", "10.0.0.5"):
        assert leak not in text
    assert "connect to <host> failed" in text


def test_sanitise_upstream_detail_caps_a_runaway_body():
    from services import llm_gateway

    text = llm_gateway._sanitise_upstream_detail("x" * 5000)
    assert len(text) <= llm_gateway._MAX_UPSTREAM_MESSAGE_CHARS


@pytest.mark.asyncio
async def test_stream_sse_emits_an_error_frame_when_the_provider_fails_mid_stream():
    """A truncated stream reads as "no response"; an error frame reads as the cause."""
    from services import llm_gateway

    async def gen():
        yield {"choices": [{"index": 0, "delta": {"content": "par"}}]}
        raise _FakeLiteLLMError('{"error":{"message":"context window exceeded"}}')

    lines = [
        line
        async for line in llm_gateway._stream_sse(
            gen(), "watsonx", "watsonx/ibm/granite-4-h-small", {"api_key": "wx-key"}
        )
    ]

    assert lines[-1] == "data: [DONE]\n\n"
    error = json.loads(lines[-2][len("data: ") :])["error"]
    assert "context window exceeded" in error["message"]
    assert error["provider"] == "watsonx"
    assert error["model"] == "watsonx/ibm/granite-4-h-small"


@pytest.mark.asyncio
async def test_stream_sse_keeps_credentials_out_of_the_error_frame():
    from services import llm_gateway

    async def gen():
        raise _FakeLiteLLMError("rejected token wx-super-secret-key")
        yield  # pragma: no cover - generator marker

    lines = [
        line
        async for line in llm_gateway._stream_sse(
            gen(), "watsonx", "watsonx/ibm/granite-4-h-small", {"api_key": "wx-super-secret-key"}
        )
    ]

    assert "wx-super-secret-key" not in "".join(lines)


@pytest.mark.asyncio
async def test_stream_sse_reports_an_empty_completion_instead_of_going_silent():
    """A 200 that carries nothing must name itself, not read as a dead connection."""
    from services import llm_gateway

    async def gen():
        yield {"choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "stop"}]}

    lines = [
        line
        async for line in llm_gateway._stream_sse(gen(), "watsonx", "watsonx/ibm/granite-4-h-small")
    ]

    assert lines[-1] == "data: [DONE]\n\n"
    error = json.loads(lines[-2][len("data: ") :])["error"]
    assert "no content and no tool calls" in error["message"]
    assert "finish_reason: stop" in error["message"]
    assert "watsonx/ibm/granite-4-h-small" in error["message"]


@pytest.mark.asyncio
async def test_stream_sse_stays_quiet_when_the_completion_carried_content():
    from services import llm_gateway

    async def gen():
        yield {"choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": "stop"}]}

    lines = [line async for line in llm_gateway._stream_sse(gen(), "openai", "gpt-4o-mini")]

    assert not any('"error"' in line for line in lines)


@pytest.mark.asyncio
async def test_stream_sse_counts_a_repaired_tool_call_as_output():
    """The repair must clear the empty-completion path, not trip it."""
    from services import llm_gateway

    async def gen():
        for chunk in _tool_call_deltas(['"{\\', 'n \\"query\\": \\"x\\"\\', 'n}"']):
            yield chunk

    lines = [
        line
        async for line in llm_gateway._stream_sse(gen(), "watsonx", "watsonx/ibm/granite-4-h-small")
    ]

    assert not any('"error"' in line for line in lines)


@pytest.mark.asyncio
async def test_stream_sse_reports_a_stream_that_never_yielded_a_chunk():
    from services import llm_gateway

    async def gen():
        return
        yield  # pragma: no cover - generator marker

    lines = [line async for line in llm_gateway._stream_sse(gen(), "openai", "gpt-4o-mini")]

    error = json.loads(lines[-2][len("data: ") :])["error"]
    assert "no content and no tool calls" in error["message"]


class TestRealFailuresReachTheBanner:
    """What the caller is told and what the banner shows must be the same text.

    The health probe issues its own request and so hits its own error. Recording
    the gateway's actual failure is what lets the banner report the one the
    user's traffic produced.
    """

    @pytest.fixture(autouse=True)
    def _clean(self):
        from services import provider_error_log

        provider_error_log.clear()
        yield
        provider_error_log.clear()

    @pytest.mark.asyncio
    async def test_a_failed_completion_is_recorded_verbatim(self, monkeypatch):
        from services import llm_gateway, provider_error_log

        monkeypatch.setattr(
            llm_gateway, "resolve_call", lambda *a, **k: ("gpt-5.6-luna", "openai", {})
        )

        async def _boom(**_kwargs):
            raise RuntimeError(
                '{"error": {"message": "Function tools with reasoning_effort are not supported"}}'
            )

        monkeypatch.setattr("litellm.acompletion", _boom)

        with pytest.raises(llm_gateway.LlmGatewayError) as raised:
            await llm_gateway.chat_completions({"model": "gpt-5.6-luna", "messages": []})

        recorded = provider_error_log.latest_failure("openai", "chat")
        assert recorded == str(raised.value)
        assert "reasoning_effort" in recorded

    @pytest.mark.asyncio
    async def test_a_later_success_clears_the_record(self, monkeypatch):
        from services import llm_gateway, provider_error_log

        provider_error_log.record_failure("openai", "chat", "stale failure")
        monkeypatch.setattr(llm_gateway, "resolve_call", lambda *a, **k: ("gpt-4o", "openai", {}))

        async def _ok(**_kwargs):
            return {"choices": [{"message": {"content": "hi"}}]}

        monkeypatch.setattr("litellm.acompletion", _ok)

        await llm_gateway.chat_completions({"model": "gpt-4o", "messages": []})

        assert provider_error_log.latest_failure("openai", "chat") is None


class TestToolsBesideReasoningEffort:
    """gpt-5.x refuses function tools next to its own default reasoning effort.

    OpenRAG never sends `reasoning_effort` — OpenAI applies a non-none default
    to reasoning models and then rejects the pair on /v1/chat/completions,
    naming an explicit "none" as the fix. `drop_params` cannot help: the
    parameter is supported, just not in that combination.
    """

    @pytest.fixture(autouse=True)
    def _clean(self):
        from services import llm_gateway, provider_error_log

        llm_gateway._TOOLS_NEED_REASONING_OFF.clear()
        provider_error_log.clear()
        yield
        llm_gateway._TOOLS_NEED_REASONING_OFF.clear()
        provider_error_log.clear()

    @staticmethod
    def _conflict() -> RuntimeError:
        return RuntimeError(
            "OpenAIException - Function tools with reasoning_effort are not supported "
            "for gpt-5.6-luna in /v1/chat/completions. To use function tools, use "
            "/v1/responses or set reasoning_effort to 'none'."
        )

    def _wire(self, monkeypatch, model="gpt-5.6-luna", supports_none=True):
        from services import llm_gateway

        monkeypatch.setattr(llm_gateway, "resolve_call", lambda *a, **k: (model, "openai", {}))
        monkeypatch.setattr(
            llm_gateway,
            "_model_info",
            lambda _m: {"supports_none_reasoning_effort": supports_none},
        )

    @pytest.mark.asyncio
    async def test_the_call_is_retried_with_reasoning_off(self, monkeypatch):
        from services import llm_gateway

        self._wire(monkeypatch)
        calls = []

        async def _flaky(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise self._conflict()
            return {"choices": [{"message": {"content": "hi"}}]}

        monkeypatch.setattr("litellm.acompletion", _flaky)

        await llm_gateway.chat_completions(
            {"model": "gpt-5.6-luna", "messages": [], "tools": [{"type": "function"}]}
        )

        assert len(calls) == 2
        assert "reasoning_effort" not in calls[0]
        assert calls[1]["reasoning_effort"] == "none"

    @pytest.mark.asyncio
    async def test_the_next_call_does_not_pay_for_the_lesson_again(self, monkeypatch):
        from services import llm_gateway

        self._wire(monkeypatch)
        calls = []

        async def _flaky(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise self._conflict()
            return {"choices": [{"message": {"content": "hi"}}]}

        monkeypatch.setattr("litellm.acompletion", _flaky)
        body = {"model": "gpt-5.6-luna", "messages": [], "tools": [{"type": "function"}]}

        await llm_gateway.chat_completions(dict(body))
        await llm_gateway.chat_completions(dict(body))

        assert len(calls) == 3
        assert calls[2]["reasoning_effort"] == "none"

    @pytest.mark.asyncio
    async def test_an_effort_the_caller_chose_is_never_overridden(self, monkeypatch):
        """Silently disabling reasoning someone asked for is worse than the error."""
        from services import llm_gateway

        self._wire(monkeypatch)
        monkeypatch.setattr(
            llm_gateway,
            "_LITELLM_FORWARDED_PARAMS",
            (*llm_gateway._LITELLM_FORWARDED_PARAMS, "reasoning_effort"),
        )
        calls = []

        async def _always_fails(**kwargs):
            calls.append(kwargs)
            raise self._conflict()

        monkeypatch.setattr("litellm.acompletion", _always_fails)

        with pytest.raises(llm_gateway.LlmGatewayError):
            await llm_gateway.chat_completions(
                {
                    "model": "gpt-5.6-luna",
                    "messages": [],
                    "tools": [{"type": "function"}],
                    "reasoning_effort": "high",
                }
            )

        assert len(calls) == 1
        assert calls[0]["reasoning_effort"] == "high"

    @pytest.mark.asyncio
    async def test_a_model_that_cannot_take_none_reports_the_error(self, monkeypatch):
        """Nothing to retry with — only the Responses API can serve tools there."""
        from services import llm_gateway

        self._wire(monkeypatch, supports_none=False)
        calls = []

        async def _always_fails(**kwargs):
            calls.append(kwargs)
            raise self._conflict()

        monkeypatch.setattr("litellm.acompletion", _always_fails)

        with pytest.raises(llm_gateway.LlmGatewayError):
            await llm_gateway.chat_completions(
                {"model": "gpt-5.6-luna", "messages": [], "tools": [{"type": "function"}]}
            )

        # Raised on the first attempt: there is no second value to try.
        assert len(calls) == 1
        assert "reasoning_effort" not in calls[0]

    @pytest.mark.asyncio
    async def test_an_unrelated_failure_is_not_retried(self, monkeypatch):
        from services import llm_gateway

        self._wire(monkeypatch)
        calls = []

        async def _no_credits(**kwargs):
            calls.append(kwargs)
            raise RuntimeError("You have no credits remaining.")

        monkeypatch.setattr("litellm.acompletion", _no_credits)

        with pytest.raises(llm_gateway.LlmGatewayError):
            await llm_gateway.chat_completions(
                {"model": "gpt-5.6-luna", "messages": [], "tools": [{"type": "function"}]}
            )

        assert len(calls) == 1
