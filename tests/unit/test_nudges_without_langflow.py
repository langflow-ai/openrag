"""Nudges bypass Langflow when DISABLE_CHAT_WITH_LANGFLOW is on.

Mirrors tests/unit/test_disable_chat_with_langflow.py: the tripwire on
ensure_langflow_client proves the bypass returns before any Langflow contact,
not merely that the result looks right.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.chat_service import ChatService  # noqa: E402
from services.llm_gateway import LlmGatewayError  # noqa: E402


class _FakeSearchService:
    """Records the kwargs it was called with; returns canned chunks."""

    def __init__(self, results=None, error=None):
        self.calls = []
        self._results = results if results is not None else [{"text": "Quarterly revenue report."}]
        self._error = error

    async def search(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        if self._error:
            raise self._error
        return {"results": self._results, "aggregations": {}, "total": len(self._results)}


def _completion(content):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


@pytest.fixture
def bypass(monkeypatch):
    """Turn the bypass on and make any Langflow contact fail loudly."""
    monkeypatch.setattr("services.chat_service.is_chat_with_langflow_disabled", lambda: True)
    monkeypatch.setattr(
        "config.settings.clients.ensure_langflow_client",
        AsyncMock(side_effect=AssertionError("Langflow should not be used")),
    )


@pytest.fixture
def llm(monkeypatch):
    """Stub the gateway; tests inspect the body it was handed."""
    mock = AsyncMock(return_value=_completion("Nudge A\nNudge B\nNudge C"))
    monkeypatch.setattr("services.nudges_service.chat_completions", mock)
    return mock


@pytest.mark.asyncio
async def test_nudges_bypass_never_touches_langflow(bypass, llm):
    search = _FakeSearchService()
    service = ChatService(search_service=search)

    result = await service.langflow_nudges_chat(user_id="oauth-user", jwt_token="jwt-token")

    assert result == {"response": "Nudge A\nNudge B\nNudge C"}
    # No conversation exists to point at, and nothing in the UI reads it.
    assert "response_id" not in result


@pytest.mark.asyncio
async def test_nudges_bypass_uses_wildcard_and_excludes_sample_data(bypass, llm):
    """With no user filters: sweep the corpus, minus the onboarding samples."""
    search = _FakeSearchService()
    service = ChatService(search_service=search)

    await service.langflow_nudges_chat(user_id="oauth-user", jwt_token="jwt-token")

    assert len(search.calls) == 1
    call = search.calls[0]
    assert call["query"] == "*"
    assert call["limit"] == 10
    assert call["filters"] is None
    assert call["exclude_sample_data"] is True
    assert call["user_id"] == "oauth-user"
    assert call["jwt_token"] == "jwt-token"


@pytest.mark.asyncio
async def test_nudges_bypass_drops_empty_filter_lists(bypass, llm):
    """An empty list means "no filter" upstream, but "match nothing" to search.

    Forwarding it verbatim would return zero chunks and silently kill nudges.
    """
    search = _FakeSearchService()
    service = ChatService(search_service=search)

    await service.langflow_nudges_chat(
        user_id="u",
        jwt_token="j",
        filters={"data_sources": ["report.pdf"], "owners": [], "document_types": None},
    )

    call = search.calls[0]
    assert call["filters"] == {"data_sources": ["report.pdf"]}
    # A real filter is active, so sample data stays in scope.
    assert call["exclude_sample_data"] is False


@pytest.mark.asyncio
async def test_nudges_bypass_forwards_limit_and_score_threshold(bypass, llm):
    """The chat page sends limit=3 and a score threshold; both must reach search."""
    search = _FakeSearchService()
    service = ChatService(search_service=search)

    await service.langflow_nudges_chat(user_id="u", jwt_token="j", limit=3, score_threshold=0.4)

    call = search.calls[0]
    assert call["limit"] == 3
    assert call["score_threshold"] == 0.4


@pytest.mark.asyncio
async def test_nudges_bypass_uses_chat_history_and_skips_retrieval(bypass, llm, monkeypatch):
    """With history present the flow ignored {docs}; skip the round-trip entirely."""
    import agent

    agent.active_conversations["db-user"] = {
        "resp-1": {
            "messages": [
                {"role": "user", "content": "What is OpenRAG?"},
                {
                    "role": "assistant",
                    "content": "It is a RAG platform.",
                    "chunks": [
                        {
                            "item": {
                                "type": "tool_call",
                                "tool_name": "search",
                                "results": ["chunk text here"],
                            }
                        }
                    ],
                },
            ]
        }
    }
    try:
        search = _FakeSearchService()
        service = ChatService(search_service=search)

        await service.langflow_nudges_chat(
            user_id="oauth-user", storage_user_id="db-user", previous_response_id="resp-1"
        )

        assert search.calls == []
        prompt = llm.await_args.args[0]["messages"][0]["content"]
        assert "user: What is OpenRAG?" in prompt
        assert "assistant: It is a RAG platform." in prompt
        assert "Context Chunks:" in prompt
        # The documents half of the template is left empty.
        assert prompt.endswith("Documents (ignore if chat history is not empty):\n")
    finally:
        agent.active_conversations.pop("db-user", None)


@pytest.mark.asyncio
async def test_nudges_bypass_sends_a_plain_completion(bypass, llm):
    """No tools, no streaming, and no model override so agent.llm_model wins."""
    service = ChatService(search_service=_FakeSearchService())

    await service.langflow_nudges_chat(user_id="u", jwt_token="j")

    body = llm.await_args.args[0]
    assert "model" not in body
    assert "tools" not in body
    assert "tool_choice" not in body
    assert "stream" not in body
    assert "max_tokens" not in body
    assert body["temperature"] == 0.1
    assert body["seed"] == 1
    assert [m["role"] for m in body["messages"]] == ["user"]


@pytest.mark.asyncio
async def test_nudges_bypass_returns_empty_when_llm_fails(bypass, monkeypatch):
    """A provider outage degrades to no nudges, never a 500 and never a leak."""
    monkeypatch.setattr(
        "services.nudges_service.chat_completions",
        AsyncMock(side_effect=LlmGatewayError("upstream refused", 502, detail="SECRET-BODY")),
    )
    service = ChatService(search_service=_FakeSearchService())

    result = await service.langflow_nudges_chat(user_id="u", jwt_token="j")

    assert result == {"response": ""}
    assert "SECRET" not in str(result)


@pytest.mark.asyncio
async def test_nudges_bypass_skips_llm_when_nothing_to_summarise(bypass, monkeypatch):
    """An empty corpus must not spend a completion."""
    monkeypatch.setattr(
        "services.nudges_service.chat_completions",
        AsyncMock(side_effect=AssertionError("LLM should not be called")),
    )
    service = ChatService(search_service=_FakeSearchService(results=[]))

    assert await service.langflow_nudges_chat(user_id="u", jwt_token="j") == {"response": ""}


@pytest.mark.asyncio
async def test_nudges_bypass_degrades_when_retrieval_raises(bypass, llm):
    """OpenSearch being down should not surface as a nudges error."""
    service = ChatService(search_service=_FakeSearchService(error=RuntimeError("opensearch down")))

    assert await service.langflow_nudges_chat(user_id="u", jwt_token="j") == {"response": ""}


@pytest.mark.asyncio
async def test_nudges_bypass_tolerates_missing_search_service(bypass, llm):
    """A bare ChatService (as tests build) must not raise."""
    service = ChatService()

    assert await service.langflow_nudges_chat(user_id="u", jwt_token="j") == {"response": ""}
