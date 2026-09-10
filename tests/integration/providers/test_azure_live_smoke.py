"""Live Azure smoke test for the runtime gateway: chat and embeddings.

`services.llm_gateway` is the single choke point for every model call OpenRAG
makes -- `/v1/chat/completions`, `/v1/embeddings`, ingest
(`models/processors.py`) and search (`services/search_service.py`) all funnel
through `chat_completions` and `embeddings`. Driving those two functions with a
real credential set is therefore the shortest path to proving that what OpenRAG
builds is what Azure accepts, and it needs no OpenSearch, Langflow or app.

Onboarding does *not* come through here -- it validates via
`api.provider_validation.validate_provider_setup`, which builds its own model
string and calls LiteLLM directly. That second path is covered by
`test_azure_live_onboarding.py`.

Skipped unless OPENRAG_LIVE_PROVIDER_TESTS=true and credentials are present;
see conftest.py for the variables.
"""

import json
import os
from typing import Any

import pytest

from services.llm_gateway import LlmGatewayError, chat_completions, embeddings

from .conftest import LiveProvider, assert_actionable_error

pytestmark = [
    pytest.mark.asyncio,
    # No OpenSearch, Langflow or app: keep the session infra fixture out of the
    # way when this directory is the only thing selected.
    pytest.mark.openrag_skip_app_onboard,
    pytest.mark.live_provider,
]

_EMBEDDING_INPUT = ["OpenRAG live provider smoke test"]

_WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_current_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
        },
    },
}


def _message(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices") or []
    assert choices, f"completion returned no choices: {payload}"
    message = choices[0].get("message")
    assert isinstance(message, dict), f"choice carried no message: {choices[0]}"
    return message


def _vector(payload: dict[str, Any]) -> list[float]:
    data = payload.get("data") or []
    assert data, f"embeddings returned no data: {payload}"
    vector = data[0]["embedding"] if isinstance(data[0], dict) else data[0].embedding
    assert isinstance(vector, list) and vector, "embedding vector is empty"
    assert all(isinstance(value, (int, float)) for value in vector)
    return vector


async def _collect_stream(stream) -> tuple[list[dict[str, Any]], bool]:
    """Parse SSE frames off the gateway stream into (frames, saw_done).

    `_stream_sse` never raises: a mid-flight failure, and an upstream 200 that
    carries nothing, both arrive as an OpenAI error *frame* followed by
    `[DONE]`. Iterating without inspecting the frames would pass on a
    completely broken stream, so callers must check what came back.
    """
    frames: list[dict[str, Any]] = []
    saw_done = False
    async for line in stream:
        payload = line.removeprefix("data:").strip()
        if not payload:
            continue
        if payload == "[DONE]":
            saw_done = True
            continue
        frames.append(json.loads(payload))
    return frames, saw_done


async def test_chat_completion_returns_content(azure_target: LiveProvider):
    """The plain chat path a user hits on every message."""
    model = azure_target.require_chat_model()

    payload = await chat_completions(
        {
            "model": f"{azure_target.provider}:{model}",
            "messages": [{"role": "user", "content": "Reply with the single word OK."}],
            "max_tokens": 16,
        },
        config=azure_target.config,
    )

    content = _message(payload).get("content")
    assert isinstance(content, str) and content.strip(), f"no content in completion: {payload}"


async def test_chat_completion_with_tools_returns_parseable_arguments(
    azure_target: LiveProvider,
):
    """Tool calling, which the agent depends on and some deployments refuse.

    Also the assertion that exercises `_repair_completion_payload` (double-
    encoded `arguments` are repaired in the gateway, not the caller) and the
    reasoning/tools retry -- a model that rejects tools beside `reasoning_effort`
    is retried once with it off.
    """
    model = azure_target.require_chat_model()

    payload = await chat_completions(
        {
            "model": f"{azure_target.provider}:{model}",
            "messages": [{"role": "user", "content": "What is the weather in Paris?"}],
            "tools": [_WEATHER_TOOL],
            "tool_choice": "required",
            "max_tokens": 128,
        },
        config=azure_target.config,
    )

    tool_calls = _message(payload).get("tool_calls")
    assert tool_calls, f"deployment {model!r} returned no tool call: {payload}"
    function = tool_calls[0]["function"]
    assert function["name"] == "get_current_weather"
    # OpenAI's contract: `arguments` is a JSON *string*. A provider that sends
    # an object, or a string encoded twice, breaks every OpenAI client.
    arguments = function["arguments"]
    assert isinstance(arguments, str), f"arguments is not a string: {arguments!r}"
    assert isinstance(json.loads(arguments), dict)


async def test_chat_completion_streams_content(azure_target: LiveProvider):
    """Streaming, asserted on frame contents because the stream never raises."""
    model = azure_target.require_chat_model()

    stream = await chat_completions(
        {
            "model": f"{azure_target.provider}:{model}",
            "messages": [{"role": "user", "content": "Count from 1 to 5."}],
            "max_tokens": 64,
            "stream": True,
        },
        config=azure_target.config,
    )
    frames, saw_done = await _collect_stream(stream)

    errors = [frame["error"] for frame in frames if "error" in frame]
    assert not errors, f"stream carried an error frame: {errors}"
    assert saw_done, "stream ended without a [DONE] frame"

    text = "".join(
        choice.get("delta", {}).get("content") or ""
        for frame in frames
        for choice in frame.get("choices") or []
    )
    assert text.strip(), f"stream delivered no content across {len(frames)} frames"


async def test_embeddings_provider_route(azure_target: LiveProvider):
    """`provider:model` -- the route search resolves for a query vector."""
    model = azure_target.require_embedding_model()

    payload = await embeddings(
        {"model": f"{azure_target.provider}:{model}", "input": _EMBEDDING_INPUT},
        config=azure_target.config,
    )

    assert len(_vector(payload)) > 0


async def test_embeddings_indexed_space_route_matches_provider_route(
    azure_target: LiveProvider,
):
    """`space:provider:model` -- the exact route ingest sends.

    `models/processors.py` embeds every chunk through this prefix so the vector
    written and the vector later queried cannot disagree about provenance.
    Asserting both routes return the same dimension is what proves they land on
    the same deployment; either alone would pass while they diverged.
    """
    model = azure_target.require_embedding_model()
    body = {"input": _EMBEDDING_INPUT}

    direct = await embeddings(
        {**body, "model": f"{azure_target.provider}:{model}"}, config=azure_target.config
    )
    indexed = await embeddings(
        {**body, "model": f"space:{azure_target.provider}:{model}"}, config=azure_target.config
    )

    assert len(_vector(indexed)) == len(_vector(direct))


async def test_wrong_api_base_produces_an_actionable_error(azure_target: LiveProvider):
    """The `/openai/v1` base URL that produced "resource not found".

    Consumes no credits -- the call cannot reach a deployment. Asserts the
    properties of the message rather than its wording, so the URL-normalisation
    work in todo-azure.md must-do #3 can change the text freely.
    """
    model = azure_target.require_chat_model()
    broken = azure_target.with_credentials(
        api_base=azure_target.credentials["api_base"].rstrip("/") + "/openai/v1"
    )

    with pytest.raises(LlmGatewayError) as excinfo:
        await chat_completions(
            {
                "model": f"{azure_target.provider}:{model}",
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 16,
            },
            config=broken.config,
        )

    assert_actionable_error(excinfo.value.message, broken.credentials["api_key"])


async def test_provider_credentials_come_only_from_config(azure_target: LiveProvider):
    """The fixture's environment scrub must leave nothing for LiteLLM to fall back on.

    A guard on the guard. LiteLLM reads `AZURE_API_KEY` / `AZURE_API_BASE` from
    the environment when a call does not carry them, so a leftover variable
    would make every test above pass even if OpenRAG stopped forwarding stored
    credentials entirely. If someone later adds a credential variable the scrub
    does not match, this fails here rather than quietly going false-green over
    there. Costs nothing -- no provider call.
    """
    leaked = sorted(name for name in os.environ if name.startswith("AZURE_"))
    assert not leaked, f"credentials still reachable through the environment: {leaked}"

    credentials = azure_target.config.providers.credential_values(azure_target.provider)
    assert credentials.get("api_key") and credentials.get("api_base"), (
        "config must be the only source of Azure credentials"
    )
