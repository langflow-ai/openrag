"""The direct chat path sends the transcript instead of chaining server-side.

Three defects shared one cause — the langflowless path sent only the bare user
string plus `previous_response_id`:

* agentd's post-tool-call follow-up passes `previous_response_id` itself, so
  supplying ours too raised "got multiple values for keyword argument";
* `DEFAULT_SYSTEM_PROMPT` was written into conversation state but never sent,
  so the agent's citation and retrieval rules never reached the model;
* server-side response chaining is an OpenAI Responses feature that providers
  routed through LiteLLM (Azure among them) need not support.
"""

import pytest
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseTextDeltaEvent,
)

import agent


def _delta(text: str, sequence: int) -> ResponseTextDeltaEvent:
    return ResponseTextDeltaEvent(
        type="response.output_text.delta",
        delta=text,
        item_id="msg_1",
        content_index=0,
        output_index=0,
        sequence_number=sequence,
        logprobs=[],
    )


def _completed(response_id: str, sequence: int) -> ResponseCompletedEvent:
    return ResponseCompletedEvent(
        type="response.completed",
        sequence_number=sequence,
        response=Response(
            id=response_id,
            created_at=0,
            model="gpt-4.1-mini",
            object="response",
            output=[],
            parallel_tool_calls=False,
            tool_choice="auto",
            tools=[],
        ),
    )


def _client(captured: dict, response_id: str = "resp_1"):
    class _Stream:
        def __aiter__(self):
            async def gen():
                yield _delta("ok", 1)
                yield _completed(response_id, 2)

            return gen()

    class _Responses:
        async def create(self, **kwargs):
            captured.clear()
            captured.update(kwargs)
            return _Stream()

    class _Client:
        default_headers: dict = {}
        api_key = "test-key"
        responses = _Responses()

    return _Client()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    agent.active_conversations.clear()

    async def _noop(user_id, session_id):
        return None

    monkeypatch.setattr(
        "services.session_ownership_service.session_ownership_service.claim_session", _noop
    )
    yield
    agent.active_conversations.clear()


@pytest.mark.asyncio
async def test_previous_response_id_is_not_forwarded_to_the_provider():
    """Sending it alongside a transcript both duplicates history and collides
    with agentd's own follow-up argument after a tool call."""
    captured: dict = {}
    async for _ in agent.async_chat_stream(
        _client(captured, "resp_2"), "q2", "user-1", previous_response_id="resp_1"
    ):
        pass

    assert "previous_response_id" not in captured


@pytest.mark.asyncio
async def test_the_system_prompt_actually_reaches_the_model():
    """Regression: it was stored in conversation state and never sent."""
    captured: dict = {}
    async for _ in agent.async_chat_stream(_client(captured), "hello", "user-1"):
        pass

    items = captured["input"]
    assert isinstance(items, list)
    assert items[0]["role"] == "system"
    assert "OpenRAG Agent" in items[0]["content"]


@pytest.mark.asyncio
async def test_history_is_replayed_on_follow_up_turns():
    captured: dict = {}
    async for _ in agent.async_chat_stream(_client(captured, "resp_1"), "first", "user-1"):
        pass
    async for _ in agent.async_chat_stream(
        _client(captured, "resp_2"),
        "second",
        "user-1",
        previous_response_id="resp_1",
        conversation_id="resp_1",
    ):
        pass

    assert [item["role"] for item in captured["input"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert [item["content"] for item in captured["input"][1:]] == ["first", "ok", "second"]


def test_only_role_and_content_survive():
    """Our stored messages carry fields the Responses API rejects."""
    state = {
        "messages": [
            {"role": "system", "content": "sys"},
            {
                "role": "user",
                "content": "q",
                "timestamp": object(),
                "chunks": [{"item": {}}],
                "response_data": {"usage": {}},
            },
            {"role": "assistant", "content": "a", "response_id": "r1"},
        ]
    }

    assert agent.conversation_input_messages(state) == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"},
    ]


def test_failed_turns_are_not_replayed_as_answers():
    """An error string must never come back as if the model had said it."""
    state = {
        "messages": [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "Server error (404)", "error": True},
            {"role": "user", "content": "retry"},
        ]
    }

    assert agent.conversation_input_messages(state) == [
        {"role": "user", "content": "q"},
        {"role": "user", "content": "retry"},
    ]


def test_empty_and_malformed_messages_are_skipped():
    state = {
        "messages": [
            {"role": "user", "content": "   "},
            {"role": "tool", "content": "tool output"},
            {"role": "user", "content": None},
            {"role": "user", "content": "kept"},
        ]
    }

    assert agent.conversation_input_messages(state) == [{"role": "user", "content": "kept"}]
