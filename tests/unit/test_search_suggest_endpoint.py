"""Endpoint-level tests for POST /search/suggest (api/search.py)."""

import json
from types import SimpleNamespace

import pytest

from api.search import SUGGEST_MAX_FILTER_VALUES, SuggestBody, suggest
from utils.opensearch_utils import DISK_SPACE_ERROR_MESSAGE, OpenSearchDiskSpaceError


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


@pytest.mark.asyncio
async def test_disk_space_error_maps_to_507():
    response = await suggest(
        SuggestBody(query="docling"),
        search_service=_Service(exc=OpenSearchDiskSpaceError(DISK_SPACE_ERROR_MESSAGE)),
        user=_user(),
    )

    assert response.status_code == 507
    assert _body(response) == {"error": DISK_SPACE_ERROR_MESSAGE}


@pytest.mark.asyncio
async def test_missing_jwt_is_forwarded_as_none():
    service = _Service({"phase": "keyword", "query": "docling", "suggestions": [], "files": []})

    response = await suggest(
        SuggestBody(query="docling"),
        search_service=service,
        user=SimpleNamespace(user_id="u1", jwt_token=None),
    )

    assert response.status_code == 200
    assert service.calls[0][1]["jwt_token"] is None


def test_request_bounds_are_enforced():
    with pytest.raises(ValueError):
        SuggestBody(query="x" * 201)
    with pytest.raises(ValueError):
        SuggestBody(query="ok", scoreThreshold=-1)
    with pytest.raises(ValueError):
        SuggestBody(query="ok", scoreThreshold=101)


def test_filter_bounds_are_enforced():
    SuggestBody(query="ok", filters={"owners": ["x"] * SUGGEST_MAX_FILTER_VALUES})
    with pytest.raises(ValueError):
        SuggestBody(query="ok", filters={"owners": ["x"] * (SUGGEST_MAX_FILTER_VALUES + 1)})
    with pytest.raises(ValueError):
        SuggestBody(query="ok", filters={f"k{i}": [] for i in range(11)})


def test_score_threshold_is_accepted_by_camel_case_name():
    assert SuggestBody.model_validate({"query": "ok", "scoreThreshold": 1.5}).scoreThreshold == 1.5
