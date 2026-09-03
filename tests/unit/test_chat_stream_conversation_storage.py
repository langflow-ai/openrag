"""A streamed langflowless reply must land in the conversation history.

Both defects here shared one cause: `async_chat_stream` was written against
Langflow's SSE shape only, so the direct OpenAI Responses path fell through
every branch silently — the sidebar stayed empty and the transcript blank,
with no error anywhere.
"""

import pytest
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseTextDeltaEvent,
)

import agent


def _delta_event(text: str, sequence: int) -> ResponseTextDeltaEvent:
    """A real SDK delta event: `delta` is a bare string, not {"content": ...}."""
    return ResponseTextDeltaEvent(
        type="response.output_text.delta",
        delta=text,
        item_id="msg_1",
        content_index=0,
        output_index=0,
        sequence_number=sequence,
        logprobs=[],
    )


def _completed_event(response_id: str, sequence: int) -> ResponseCompletedEvent:
    """The terminal event. The id lives on `response`, never at the top level."""
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


def _client(events):
    class _Stream:
        def __aiter__(self):
            async def gen():
                for event in events:
                    yield event

            return gen()

    class _Responses:
        async def create(self, **kwargs):
            return _Stream()

    class _Client:
        default_headers: dict = {}
        api_key = "test-key"
        responses = _Responses()

    return _Client()


async def _noop_claim(user_id, session_id):
    return None


@pytest.fixture(autouse=True)
def _clean_conversations():
    agent.active_conversations.clear()
    yield
    agent.active_conversations.clear()


@pytest.mark.asyncio
async def test_streamed_reply_is_stored_under_the_real_response_id(monkeypatch):
    """Regression: the sidebar was empty after every langflowless chat.

    `store_conversation_thread` is gated on a resolved response_id, and the
    OpenAI Responses stream carries none at the top level — so nothing was ever
    stored.
    """
    stored = {}

    async def _capture(user_id, response_id, state):
        stored[response_id] = state

    monkeypatch.setattr(agent, "store_conversation_thread", _capture)

    events = [_delta_event("Hello", 1), _delta_event(" world", 2), _completed_event("resp_abc", 3)]
    async for _ in agent.async_chat_stream(_client(events), "hi", "user-1"):
        pass

    assert list(stored) == ["resp_abc"]


@pytest.mark.asyncio
async def test_streamed_reply_text_reaches_the_transcript():
    """Regression: conversations were stored with an empty assistant message.

    `"content" in delta` is a substring test when delta is a string, so the
    OpenAI shape accumulated nothing while the UI still rendered the reply.
    """
    events = [_delta_event("Hello", 1), _delta_event(" world", 2), _completed_event("resp_abc", 3)]
    async for _ in agent.async_chat_stream(_client(events), "hi", "user-1"):
        pass

    messages = agent.active_conversations["user-1"]["resp_abc"]["messages"]
    assistant = [m for m in messages if m["role"] == "assistant"]
    assert [m["content"] for m in assistant] == ["Hello world"]


@pytest.mark.asyncio
async def test_langflow_delta_shape_still_accumulates():
    """Langflow wraps deltas as {"content": ...}; both shapes must work."""
    assert agent._extract_delta_text({"content": "from langflow"}) == "from langflow"
    assert agent._extract_delta_text("from openai") == "from openai"
    # Shapes that carry no text must contribute nothing rather than str(dict).
    assert agent._extract_delta_text({"content": ""}) == ""
    assert agent._extract_delta_text(None) == ""


@pytest.mark.asyncio
async def test_a_top_level_id_still_wins_when_present(monkeypatch):
    """Langflow's SSE sends a top-level id and a dict delta — do not regress it."""
    stored = {}

    async def _capture(user_id, response_id, state):
        stored[response_id] = state

    monkeypatch.setattr(agent, "store_conversation_thread", _capture)

    # No model_dump, so the stream serializes __dict__ — Langflow's chunk shape.
    class _LangflowChunk:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    events = [_LangflowChunk(id="lf-123", delta={"content": "hi there"})]
    async for _ in agent.async_chat_stream(_client(events), "hi", "user-1"):
        pass

    assert list(stored) == ["lf-123"]
    assistant = [m for m in stored["lf-123"]["messages"] if m["role"] == "assistant"]
    assert [m["content"] for m in assistant] == ["hi there"]


@pytest.mark.asyncio
async def test_nothing_is_stored_when_the_stream_never_completes(monkeypatch):
    """No terminal event means no id, and storing under a guess would be wrong."""
    stored = {}

    async def _capture(user_id, response_id, state):
        stored[response_id] = state

    monkeypatch.setattr(agent, "store_conversation_thread", _capture)

    async for _ in agent.async_chat_stream(_client([_delta_event("partial", 1)]), "hi", "user-1"):
        pass

    assert stored == {}


@pytest.mark.asyncio
async def test_streamed_reply_claims_session_ownership(monkeypatch):
    """Regression: the next message in the thread 404'd.

    `_assert_owns` returns 404 (session_not_found) for an unclaimed session, and
    the langflowless paths stored conversations without ever claiming them —
    only the Langflow variants did. Invisible until threading worked.
    """
    claimed = []

    async def _claim(user_id, session_id):
        claimed.append((user_id, session_id))

    monkeypatch.setattr(
        "services.session_ownership_service.session_ownership_service.claim_session", _claim
    )

    events = [_delta_event("Hello", 1), _completed_event("resp_abc", 2)]
    async for _ in agent.async_chat_stream(_client(events), "hi", "user-1"):
        pass

    assert claimed == [("user-1", "resp_abc")]


@pytest.mark.asyncio
async def test_non_streaming_reply_also_claims_session_ownership(monkeypatch):
    """The blocking path stores a conversation too, so it must claim as well."""
    claimed = []

    async def _claim(user_id, session_id):
        claimed.append((user_id, session_id))

    monkeypatch.setattr(
        "services.session_ownership_service.session_ownership_service.claim_session", _claim
    )

    class _Response:
        id = "resp_nonstream"
        output_text = "Hello world"

        def model_dump(self):
            return {"id": self.id}

    class _Responses:
        async def create(self, **kwargs):
            return _Response()

    class _Client:
        default_headers: dict = {}
        api_key = "test-key"
        responses = _Responses()

    text, response_id = await agent.async_chat(_Client(), "hi", "user-1")

    assert (text, response_id) == ("Hello world", "resp_nonstream")
    assert claimed == [("user-1", "resp_nonstream")]


@pytest.mark.asyncio
async def test_a_claim_failure_never_loses_the_reply(monkeypatch):
    """A claim is best effort: the user already saw the answer."""

    async def _boom(user_id, session_id):
        raise RuntimeError("ownership store unavailable")

    monkeypatch.setattr(
        "services.session_ownership_service.session_ownership_service.claim_session", _boom
    )

    events = [_delta_event("Hello", 1), _completed_event("resp_abc", 2)]
    async for _ in agent.async_chat_stream(_client(events), "hi", "user-1"):
        pass

    # Stored despite the claim failing.
    assert "resp_abc" in agent.active_conversations["user-1"]


@pytest.mark.asyncio
async def test_a_multi_turn_thread_stays_on_one_sidebar_entry(monkeypatch):
    """Regression: the sidebar grew one duplicate entry per message.

    Conversations were stored under the per-turn provider response id, so each
    follow-up created a second row carrying the same title (the thread's first
    user message). conversation_id is the stable sidebar thread id.
    """
    monkeypatch.setattr(
        "services.session_ownership_service.session_ownership_service.claim_session",
        _noop_claim,
    )

    # Turn 1 opens the thread.
    async for _ in agent.async_chat_stream(
        _client([_delta_event("first", 1), _completed_event("resp_1", 2)]), "q1", "user-1"
    ):
        pass
    thread_id = next(iter(agent.active_conversations["user-1"]))
    assert thread_id == "resp_1"

    # Turn 2 continues it, the way the client replays the ids.
    async for _ in agent.async_chat_stream(
        _client([_delta_event("second", 1), _completed_event("resp_2", 2)]),
        "q2",
        "user-1",
        previous_response_id="resp_1",
        conversation_id=thread_id,
    ):
        pass

    assert list(agent.active_conversations["user-1"]) == ["resp_1"], (
        "a follow-up must not create a second sidebar entry"
    )
    contents = [
        m["content"]
        for m in agent.active_conversations["user-1"]["resp_1"]["messages"]
        if m["role"] in ("user", "assistant")
    ]
    assert contents == ["q1", "first", "q2", "second"]


@pytest.mark.asyncio
async def test_the_provider_response_id_is_claimed_even_when_it_is_not_the_thread_id(monkeypatch):
    """The client replays the provider id, and _assert_owns 404s if unclaimed."""
    claimed = []

    async def _claim(user_id, session_id):
        claimed.append(session_id)

    monkeypatch.setattr(
        "services.session_ownership_service.session_ownership_service.claim_session", _claim
    )

    async for _ in agent.async_chat_stream(
        _client([_delta_event("first", 1), _completed_event("resp_1", 2)]), "q1", "user-1"
    ):
        pass
    claimed.clear()

    async for _ in agent.async_chat_stream(
        _client([_delta_event("second", 1), _completed_event("resp_2", 2)]),
        "q2",
        "user-1",
        previous_response_id="resp_1",
        conversation_id="resp_1",
    ):
        pass

    assert set(claimed) == {"resp_1", "resp_2"}
