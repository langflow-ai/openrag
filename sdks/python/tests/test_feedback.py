import json

import httpx
import pytest

from openrag_sdk import (
    AuthenticationError,
    FeedbackResponse,
    NotFoundError,
    OpenRAGClient,
    ValidationError,
)

HISTORY_FEEDBACK = {
    "rating": "up",
    "comment": None,
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
}
SAVED = {
    "message_id": "m1",
    "rating": "up",
    "comment": None,
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
}


def make_client(handler):
    client = OpenRAGClient(api_key="orag_test", base_url="http://test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


async def test_feedback_posts_full_value_to_message_route():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["path"] = request.method, request.url.raw_path.decode()
        seen["body"] = json.loads(request.content)
        seen["key"] = request.headers.get("x-api-key") or request.headers.get(
            "authorization"
        )
        return httpx.Response(200, json=SAVED)

    async with make_client(handler) as client:
        out = await client.chat.feedback("chat/1", "m1", "up")
    assert isinstance(out, FeedbackResponse) and out.rating == "up"
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/chat/chat%2F1/messages/m1/feedback"
    assert seen["body"] == {"rating": "up", "comment": None}
    assert "orag_test" in seen["key"]


async def test_feedback_sends_comment():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={**SAVED, "rating": "down", "comment": "bad"})

    async with make_client(handler) as client:
        out = await client.chat.feedback("c", "m1", "down", comment="bad")
    assert bodies == [{"rating": "down", "comment": "bad"}]
    assert out.comment == "bad"


@pytest.mark.parametrize(
    "status,exc",
    [(403, AuthenticationError), (404, NotFoundError), (422, ValidationError)],
)
async def test_feedback_non_2xx_errors(status, exc):
    def handler(request):
        return httpx.Response(status, json={"detail": {"error": "x"}})

    async with make_client(handler) as client:
        with pytest.raises(exc):
            await client.chat.feedback("c", "m1", "up")


async def test_chat_response_and_history_expose_message_ids():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "response": "a",
                    "chat_id": "c",
                    "sources": [],
                    "message_id": "m9",
                },
            )
        return httpx.Response(
            200,
            json={
                "chat_id": "c",
                "messages": [
                    {"role": "user", "content": "q"},
                    {
                        "role": "assistant",
                        "content": "a",
                        "message_id": "m9",
                        "feedback": SAVED,
                    },
                ],
            },
        )

    async with make_client(handler) as client:
        created = await client.chat.create(message="q")
        detail = await client.chat.get("c")
    assert created.message_id == "m9"
    assert detail.messages[0].message_id is None
    assert detail.messages[1].message_id == "m9"
    assert detail.messages[1].feedback.rating == "up"


async def test_stream_done_event_carries_message_id():
    sse = (
        'data: {"type":"content","delta":"hi"}\n\n'
        'data: {"type":"done","chat_id":"c","message_id":"m5"}\n\n'
    )

    def handler(request):
        return httpx.Response(
            200, content=sse, headers={"content-type": "text/event-stream"}
        )

    async with make_client(handler) as client:
        async with client.chat.stream(message="q") as stream:
            events = [e async for e in stream]
        assert stream.message_id == "m5"
    assert events[-1].message_id == "m5"
