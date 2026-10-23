"""Regression coverage: the direct (non-Langflow) chat path must use the
configured `agent.llm_model`, not agent.py's hardcoded "gpt-4.1-mini"
default (openrag issue #2060 follow-up).

Before this fix, `ChatService.chat()` and the "chat" branch of
`ChatService.upload_context_chat()` called `async_chat`/`async_chat_stream`
without a `model=` kwarg, so they silently fell back to the hardcoded
default regardless of what model was actually configured - breaking direct
chat against a self-hosted gateway whose only route is a non-default model
name. The upload_context_chat "chat" branch also referenced `config`, a name
only bound in the sibling "langflow" branch, which would have raised
NameError at runtime.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import config.settings as settings_module  # noqa: E402
from services.chat_service import ChatService  # noqa: E402

CONFIGURED_MODEL = "cohere-embed-multilingual-bedrock"


def _fake_config():
    config = MagicMock()
    config.agent.llm_model = CONFIGURED_MODEL
    return config


@pytest.fixture(autouse=True)
def _stub_patched_llm_client(monkeypatch):
    """`clients.patched_llm_client` is a read-only property with a side
    effect (falls back to mutating the real os.environ["OPENAI_API_KEY"]
    when no key is configured - see config/settings.py). Chat-service call
    sites evaluate it eagerly as a plain function argument even when the
    downstream `async_chat`/`async_chat_stream` call itself is mocked, so it
    must be stubbed at the class level here to keep these tests isolated
    from process env state and from needing real provider credentials."""
    monkeypatch.setattr(
        type(settings_module.clients), "patched_llm_client", property(lambda self: object())
    )


@pytest.mark.asyncio
async def test_chat_non_streaming_passes_configured_model(monkeypatch):
    monkeypatch.setattr("config.settings.get_openrag_config", lambda: _fake_config())
    async_chat_mock = AsyncMock(return_value=("response text", "response-id"))
    monkeypatch.setattr("services.chat_service.async_chat", async_chat_mock)

    chat_svc = ChatService()
    await chat_svc.chat(prompt="hello")

    assert async_chat_mock.await_args.kwargs["model"] == CONFIGURED_MODEL


@pytest.mark.asyncio
async def test_chat_streaming_passes_configured_model(monkeypatch):
    monkeypatch.setattr("config.settings.get_openrag_config", lambda: _fake_config())
    async_chat_stream_mock = MagicMock(return_value=iter([]))
    monkeypatch.setattr("services.chat_service.async_chat_stream", async_chat_stream_mock)

    chat_svc = ChatService()
    await chat_svc.chat(prompt="hello", stream=True)

    assert async_chat_stream_mock.call_args.kwargs["model"] == CONFIGURED_MODEL


@pytest.mark.asyncio
async def test_upload_context_chat_direct_endpoint_passes_configured_model(monkeypatch):
    """The "chat" (non-Langflow) branch of upload_context_chat - previously
    broken by a NameError on the unbound `config` name."""
    monkeypatch.setattr("config.settings.get_openrag_config", lambda: _fake_config())
    async_chat_mock = AsyncMock(return_value=("response text", "response-id"))
    monkeypatch.setattr("services.chat_service.async_chat", async_chat_mock)

    chat_svc = ChatService()
    await chat_svc.upload_context_chat(
        document_content="content", filename="doc.txt", endpoint="chat"
    )

    assert async_chat_mock.await_args.kwargs["model"] == CONFIGURED_MODEL
