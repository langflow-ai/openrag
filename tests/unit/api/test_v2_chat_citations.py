import json
import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from api.v1.chat import ChatV1Body, chat_create_endpoint
from api.v2.chat import _build_search_results, chat_v2_create_endpoint
from session_manager import User


def test_build_search_results_transformation():
    sources = [
        {
            "filename": "annual_report.pdf",
            "text": "Revenue increased by 15% in Q4.",
            "score": 0.95,
            "page": 12,
            "mimetype": "application/pdf",
            "source_url": "https://example.com/docs/annual_report.pdf",
        },
        {
            "filename": "readme.txt",
            "text": "System installation instructions.",
            "score": 0.82,
        },
    ]

    results = _build_search_results(sources)

    assert len(results) == 2
    assert results[0] == {
        "title": "annual_report.pdf",
        "body": "Revenue increased by 15% in Q4.",
        "url": "https://example.com/docs/annual_report.pdf",
    }
    assert results[1] == {
        "title": "readme.txt",
        "body": "System installation instructions.",
        "url": "",
    }


@pytest.mark.asyncio
async def test_v2_chat_endpoint_returns_citations_and_search_results():
    class DummyChatService:
        async def langflow_chat(self, **kwargs):
            return {
                "response": "Here is the summary.",
                "response_id": "chat-12345",
                "sources": [
                    {
                        "filename": "kb_doc.pdf",
                        "text": "Detailed information snippet.",
                        "score": 0.88,
                        "source_url": "https://kb.example.com/doc.pdf",
                    }
                ],
            }

    dummy_request = Request(
        scope={
            "type": "http",
            "headers": [(b"x-request-id", b"req-test-123")],
        }
    )

    dummy_user = User(
        user_id="user-123",
        name="Test User",
        email="test@example.com",
        jwt_token="dummy-jwt",
    )

    body = ChatV1Body(message="Summarize the doc", stream=False)

    response = await chat_v2_create_endpoint(
        body=body,
        request=dummy_request,
        chat_service=DummyChatService(),
        session_manager=None,
        user=dummy_user,
        knowledge_filter_service=None,
    )

    assert isinstance(response, JSONResponse)
    data = json.loads(response.body.decode("utf-8"))

    assert data["response"] == "Here is the summary."
    assert data["chat_id"] == "chat-12345"
    assert len(data["sources"]) == 1
    assert data["search_results"] == [
        {
            "title": "kb_doc.pdf",
            "body": "Detailed information snippet.",
            "url": "https://kb.example.com/doc.pdf",
        }
    ]
    assert data["citations_shown"] == -1


@pytest.mark.asyncio
async def test_v1_chat_endpoint_remains_unchanged():
    class DummyChatService:
        async def langflow_chat(self, **kwargs):
            return {
                "response": "Here is the summary.",
                "response_id": "chat-12345",
                "sources": [
                    {
                        "filename": "kb_doc.pdf",
                        "text": "Detailed information snippet.",
                        "score": 0.88,
                    }
                ],
            }

    dummy_request = Request(
        scope={
            "type": "http",
            "headers": [(b"x-request-id", b"req-test-123")],
        }
    )

    dummy_user = User(
        user_id="user-123",
        name="Test User",
        email="test@example.com",
        jwt_token="dummy-jwt",
    )

    body = ChatV1Body(message="Summarize the doc", stream=False)

    response = await chat_create_endpoint(
        body=body,
        request=dummy_request,
        chat_service=DummyChatService(),
        session_manager=None,
        user=dummy_user,
        knowledge_filter_service=None,
    )

    assert isinstance(response, JSONResponse)
    data = json.loads(response.body.decode("utf-8"))

    assert data["response"] == "Here is the summary."
    assert data["chat_id"] == "chat-12345"
    assert len(data["sources"]) == 1
    assert "search_results" not in data
    assert "citations_shown" not in data
