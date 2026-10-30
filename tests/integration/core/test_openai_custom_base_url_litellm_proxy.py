"""Real end-to-end integration test for the OpenAI custom base-URL override
(openrag issue #2060), exercised against a locally running LiteLLM proxy.

Chain under test: OpenRAG config (openai_base_url) -> real OpenAI SDK
(AsyncOpenAI via AppClients.patched_async_client) -> real HTTP call to the
local LiteLLM proxy -> a mock embeddings stub behind it, which logs every
call (including any `input_type`) to /tmp/mock_stub_calls.jsonl.

This proves two things end to end:
  1. The configured base_url actually reaches the real OpenAI SDK client and
     the LiteLLM proxy responds successfully through it.
  2. `extra_body={"input_type": ...}` passed to `.embeddings.create()` is
     forwarded into the raw JSON request body the proxy (and the stub behind
     it) receives - the passthrough mechanism this code path relies on for
     provider-specific embedding params.

NOTE on `litellm.register_model` below: this is a pre-existing constraint of
the `agentd` package (not something introduced by this change). Its patched
`.embeddings.create()` calls `litellm.utils.get_llm_provider(model)` with no
`api_base`/`custom_llm_provider` hint before doing anything else; for a bare
model name litellm doesn't already recognize (like this proxy's
"cohere-embed-multilingual-bedrock" route alias), that raises
`BadRequestError` before any HTTP request is made - confirmed by running this
test without the registration call. Prefixing the model with "openai/"
avoids that, but then the LiteLLM proxy 400s because its route table matches
model names literally (also confirmed via a manual curl). Registering the
model name with litellm as provider "openai" is litellm's own supported
mechanism for exactly this "custom endpoint, alias model name" situation,
and only affects local provider classification - it does not stub out any
part of the network chain this test is verifying.

Requires:
  - A LiteLLM proxy at LITELLM_PROXY_URL with a "cohere-embed-multilingual-bedrock"
    model route pointed at a mock stub that appends one JSON line per call to
    MOCK_STUB_LOG.
This is a fixture already running on the host for this task; the test skips
itself (rather than failing) if it isn't reachable, so it degrades cleanly
in environments without that fixture (e.g. plain CI).
"""

import json
import os
from pathlib import Path
from unittest import mock

import httpx
import litellm
import pytest

import config.settings as settings_module
from config.config_manager import (
    AgentConfig,
    AnthropicConfig,
    KnowledgeConfig,
    OllamaConfig,
    OnboardingState,
    OpenAIConfig,
    OpenRAGConfig,
    ProvidersConfig,
    WatsonXConfig,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.openrag_skip_app_onboard,
]

LITELLM_PROXY_URL = "http://localhost:4444/v1"
LITELLM_MASTER_KEY = "sk-test-master-key-local-only"
EMBEDDING_MODEL = "cohere-embed-multilingual-bedrock"
MOCK_STUB_LOG = Path("/tmp/mock_stub_calls.jsonl")


def _proxy_is_reachable() -> bool:
    try:
        resp = httpx.post(
            f"{LITELLM_PROXY_URL}/embeddings",
            headers={
                "Authorization": f"Bearer {LITELLM_MASTER_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": EMBEDDING_MODEL, "input": ["connectivity-check"]},
            timeout=5.0,
        )
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _make_openrag_config() -> OpenRAGConfig:
    return OpenRAGConfig(
        providers=ProvidersConfig(
            openai=OpenAIConfig(
                api_key=LITELLM_MASTER_KEY,
                base_url=LITELLM_PROXY_URL,
                configured=True,
            ),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
        ),
        knowledge=KnowledgeConfig(
            embedding_model=EMBEDDING_MODEL,
            embedding_provider="openai",
        ),
        agent=AgentConfig(llm_model="gpt-5.4-mini", llm_provider="openai"),
        onboarding=OnboardingState(),
        edited=True,
    )


@pytest.fixture(autouse=True)
def _restore_environ():
    original = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(original)


@pytest.mark.skipif(
    not _proxy_is_reachable(),
    reason=(
        "Local LiteLLM proxy not reachable at "
        f"{LITELLM_PROXY_URL} - skipping the real-proxy integration test."
    ),
)
async def test_custom_base_url_reaches_real_litellm_proxy_with_input_type_passthrough():
    # See module docstring: teaches litellm's local provider-detection table
    # that this proxy route alias belongs to "openai" so agentd's patched
    # client forwards the call to the real OpenAI SDK against our base_url
    # instead of raising BadRequestError before any network call happens.
    litellm.register_model(
        {EMBEDDING_MODEL: {"litellm_provider": "openai", "mode": "embedding"}}
    )

    fake_config = _make_openrag_config()
    app_clients = settings_module.AppClients()

    with mock.patch.object(settings_module, "get_openrag_config", lambda: fake_config):
        client = app_clients.patched_async_client

        try:
            # Snapshot the stub's call log *after* client construction (the
            # HTTP/2 probe itself makes one real call against the configured
            # base_url) so we only assert on the call we make explicitly below.
            before = _read_jsonl(MOCK_STUB_LOG)

            response = await client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=["hello"],
                extra_body={"input_type": "search_document"},
            )

            assert response.data
            assert len(response.data[0].embedding) > 0

            after = _read_jsonl(MOCK_STUB_LOG)
            new_entries = after[len(before) :]
            assert new_entries, "expected the mock stub to log our embeddings.create call"

            last_call = new_entries[-1]
            assert last_call["input_type"] == "search_document", (
                f"expected input_type to reach the stub via extra_body, got: {last_call}"
            )
            assert last_call["model"], f"expected a non-empty model on the stub call, got: {last_call}"
        finally:
            await app_clients.close()
