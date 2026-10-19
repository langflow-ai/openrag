"""Endpoint-level tests for POST /search/suggest (api/search.py)."""

import json
from types import SimpleNamespace

import pytest

from api.search import SuggestBody, suggest


class _Service:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    async def suggest(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if self.exc:
            raise self.exc
        return self.result


def _user():
    return SimpleNamespace(user_id="u1", jwt_token="jwt")


def _body(response):
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_forwards_request_and_returns_payload():
    payload = {"phase": "keyword", "query": "docling", "suggestions": [], "files": []}
    service = _Service(payload)

    response = await suggest(
        SuggestBody(query="docling", filters={"owners": ["x"]}, semantic=True, scoreThreshold=2),
        search_service=service,
        user=_user(),
    )

    assert response.status_code == 200
    assert _body(response) == payload
    assert service.calls == [
        (
            "docling",
            {
                "user_id": "u1",
                "jwt_token": "jwt",
                "filters": {"owners": ["x"]},
                "semantic": True,
                "score_threshold": 2,
            },
        )
    ]


@pytest.mark.asyncio
async def test_internal_errors_are_not_leaked_to_the_client():
    response = await suggest(
        SuggestBody(query="docling"),
        search_service=_Service(exc=RuntimeError("secret connection string")),
        user=_user(),
    )

    assert response.status_code == 500
    assert _body(response) == {"error": "Suggestions unavailable"}


@pytest.mark.asyncio
async def test_service_error_payload_becomes_generic_502():
    response = await suggest(
        SuggestBody(query="docling"),
        search_service=_Service({"error": "embedding provider detail"}),
        user=_user(),
    )

    assert response.status_code == 502
    assert "embedding provider detail" not in response.body.decode()


def test_request_bounds_are_enforced():
    with pytest.raises(ValueError):
        SuggestBody(query="x" * 201)
    with pytest.raises(ValueError):
        SuggestBody(query="ok", scoreThreshold=-1)
