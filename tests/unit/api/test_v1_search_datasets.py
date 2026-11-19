"""/v1/search with imported datasets: selection precedence, RRF merge, compatibility."""

import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.v1 import search as v1_search
from services import dataset_search_service as dss


@dataclass(frozen=True)
class Rec:
    id: str


DOC_HITS = [
    {
        "chunk_id": "doc-1",
        "filename": "report.pdf",
        "text": "doc one",
        "score": 9.0,
        "page": 2,
        "mimetype": "application/pdf",
        "owner": "someone",
    },
    {
        "chunk_id": "doc-2",
        "filename": "notes.txt",
        "text": "doc two",
        "score": 4.0,
        "page": None,
        "mimetype": "text/plain",
    },
]


def _dataset_hit(dataset_id, n):
    return {
        "chunk_id": f"ds-{dataset_id}-{n}",
        "filename": f"Set {dataset_id} / record {n}",
        "text": f"record {n}",
        "score": 3.0,
        "page": None,
        "mimetype": "application/x-opensearch-document",
        "dataset": {
            "id": dataset_id,
            "name": f"Set {dataset_id}",
            "import_name": "Import",
            "source_index": "src",
        },
    }


class FakeDatasetSearch:
    instances: list = []

    def __init__(self, session_manager):
        self.session_manager = session_manager
        self.calls: list[dict] = []
        type(self).instances.append(self)

    async def search(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        hits = [_dataset_hit(i, n) for i in kwargs["dataset_ids"] for n in (1, 2)]
        return {"results": hits[: kwargs["limit"]], "errors": list(type(self).errors)}


class Env:
    def __init__(self):
        self.visible = [Rec("a"), Rec("b"), Rec("c")]
        self.available = True
        self.looked_up_for: list = []
        self.doc_calls: list[dict] = []
        self.doc_hits = DOC_HITS
        self.saved_filters: dict | None = None


@pytest.fixture
def env(monkeypatch):
    state = Env()
    FakeDatasetSearch.instances = []
    FakeDatasetSearch.errors = []

    async def list_visible(user_id):
        state.looked_up_for.append(user_id)
        return list(state.visible)

    monkeypatch.setattr(dss, "snapshot_import_available", lambda: state.available)
    monkeypatch.setattr(dss, "list_visible_datasets", list_visible)
    monkeypatch.setattr(v1_search, "DatasetSearchService", FakeDatasetSearch)

    async def resolve(*_args, **_kwargs):
        return {"filters": state.saved_filters or {}, "limit": 10, "score_threshold": 0}

    monkeypatch.setattr(v1_search, "resolve_filter_id", resolve)
    return state


def _doc_service(env):
    async def search(query, **kwargs):
        env.doc_calls.append({"query": query, **kwargs})
        return {"results": [dict(hit) for hit in env.doc_hits]}

    return SimpleNamespace(search=search, session_manager="session-manager")


async def _call(env, **body):
    response = await v1_search.search_endpoint(
        v1_search.SearchV1Body(query="q", **body),
        search_service=_doc_service(env),
        user=SimpleNamespace(user_id="auth-user", jwt_token="jwt"),
        knowledge_filter_service=None,
    )
    return response.status_code, json.loads(response.body)


def _searched(env):
    return [call["dataset_ids"] for i in FakeDatasetSearch.instances for call in i.calls]


@pytest.mark.asyncio
async def test_unavailable_feature_behaves_like_documents_only_search(env):
    env.available = False

    status, payload = await _call(env, limit=5, filters={"owners": ["x"]})

    assert status == 200
    assert payload == {
        "results": [
            {
                "filename": "report.pdf",
                "text": "doc one",
                "score": 9.0,
                "page": 2,
                "mimetype": "application/pdf",
                "dataset": None,
            },
            {
                "filename": "notes.txt",
                "text": "doc two",
                "score": 4.0,
                "page": None,
                "mimetype": "text/plain",
                "dataset": None,
            },
        ]
    }
    assert env.looked_up_for == [] and FakeDatasetSearch.instances == []
    assert env.doc_calls[0]["filters"] == {"owners": ["x"]}
    assert env.doc_calls[0]["limit"] == 5


@pytest.mark.asyncio
async def test_available_feature_merges_documents_and_dataset_records_by_rrf(env):
    status, payload = await _call(env, limit=4)

    assert status == 200
    assert env.looked_up_for == ["auth-user"]
    (searched,) = _searched(env)
    assert searched == ["a", "b", "c"]
    results = payload["results"]
    assert len(results) == 4
    assert {r["filename"] for r in results} >= {"report.pdf", "notes.txt"}
    datasets = [r["dataset"] for r in results if r["dataset"]]
    assert datasets and set(datasets[0]) == {"id", "name", "import_name", "source_index"}
    # Every result carries the five long-standing fields plus `dataset`.
    assert all(
        set(r) == {"filename", "text", "score", "page", "mimetype", "dataset"} for r in results
    )
    assert all(
        r["dataset"] is None
        for r in results
        if r["mimetype"] != "application/x-opensearch-document"
    )
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_dataset_search_runs_as_the_caller_with_the_request_limit(env):
    await _call(env, limit=7)

    (instance,) = FakeDatasetSearch.instances
    assert instance.session_manager == "session-manager"
    assert instance.calls[0]["user_id"] == "auth-user"
    assert instance.calls[0]["jwt_token"] == "jwt"
    assert instance.calls[0]["limit"] == 7


@pytest.mark.asyncio
async def test_empty_datasets_list_means_documents_only_with_untouched_scores(env):
    status, payload = await _call(env, datasets=[])

    assert status == 200
    assert FakeDatasetSearch.instances == [] and env.looked_up_for == []
    assert [r["score"] for r in payload["results"]] == [9.0, 4.0]
    assert all(r["dataset"] is None for r in payload["results"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,saved,expected",
    [
        ({}, None, ["a", "b", "c"]),
        ({"datasets": "*"}, None, ["a", "b", "c"]),
        ({"datasets": ["b", "ghost"]}, None, ["b"]),
        # body field beats inline filters beats saved filter
        (
            {"datasets": ["a"], "filters": {"datasets": ["b"]}, "filter_id": "f"},
            {"datasets": ["c"]},
            ["a"],
        ),
        ({"filters": {"datasets": ["b"]}, "filter_id": "f"}, {"datasets": ["c"]}, ["b"]),
        ({"filter_id": "f"}, {"datasets": ["c"]}, ["c"]),
        # a saved filter that does not mention datasets selects all
        ({"filter_id": "f"}, {"owners": ["x"]}, ["a", "b", "c"]),
        # "*" higher up overrides a narrower saved filter
        ({"filters": {"datasets": ["*"]}, "filter_id": "f"}, {"datasets": ["c"]}, ["a", "b", "c"]),
    ],
)
async def test_selection_precedence(env, body, saved, expected):
    env.saved_filters = saved

    status, _ = await _call(env, **body)

    assert status == 200
    assert _searched(env) == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,saved",
    [
        ({"datasets": []}, {"datasets": ["c"]}),
        ({"filters": {"datasets": []}, "filter_id": "f"}, {"datasets": ["c"]}),
        ({"filter_id": "f"}, {"datasets": []}),
    ],
)
async def test_empty_list_at_any_level_selects_no_datasets(env, body, saved):
    env.saved_filters = saved

    status, payload = await _call(env, **body)

    assert status == 200
    assert _searched(env) == []
    assert [r["score"] for r in payload["results"]] == [9.0, 4.0]


@pytest.mark.asyncio
async def test_selecting_datasets_the_user_cannot_see_searches_nothing(env):
    env.visible = [Rec("a")]

    status, payload = await _call(env, datasets=["b", "c"])

    assert status == 200
    assert _searched(env) == []
    assert all(r["dataset"] is None for r in payload["results"])


@pytest.mark.asyncio
async def test_datasets_filter_key_never_becomes_a_document_clause(env, monkeypatch):
    """The document search receives the key but ignores it (see search_service)."""
    from services.search_service import _build_search_filter_clauses

    assert _build_search_filter_clauses({"datasets": ["a"]}) == []
    assert _build_search_filter_clauses({"datasets": [], "owners": ["x"]}) == [
        {"term": {"owner": "x"}}
    ]

    await _call(env, filters={"datasets": ["a"], "owners": ["x"]})

    assert env.doc_calls[0]["filters"] == {"datasets": ["a"], "owners": ["x"]}


@pytest.mark.asyncio
async def test_dataset_failures_are_reported_without_failing_documents(env):
    FakeDatasetSearch.errors = [{"dataset_id": "a", "code": "forbidden"}]

    status, payload = await _call(env)

    assert status == 200
    assert payload["dataset_errors"] == [{"dataset_id": "a", "code": "forbidden"}]
    assert {"report.pdf", "notes.txt"} <= {r["filename"] for r in payload["results"]}


@pytest.mark.asyncio
async def test_no_dataset_errors_key_when_nothing_failed(env):
    _, payload = await _call(env)

    assert "dataset_errors" not in payload


@pytest.mark.asyncio
async def test_registry_failure_does_not_break_document_search(env, monkeypatch):
    monkeypatch.setattr(dss, "list_visible_datasets", AsyncMock(side_effect=RuntimeError("db")))

    status, payload = await _call(env)

    assert status == 200
    assert [r["filename"] for r in payload["results"]] == ["report.pdf", "notes.txt"]
    assert payload["dataset_errors"] == [{"dataset_id": None, "code": "lookup_failed"}]


@pytest.mark.asyncio
async def test_dataset_search_without_hits_leaves_document_scores_alone(env, monkeypatch):
    class Empty(FakeDatasetSearch):
        async def search(self, query, **kwargs):
            return {"results": [], "errors": []}

    monkeypatch.setattr(v1_search, "DatasetSearchService", Empty)

    _, payload = await _call(env)

    assert [r["score"] for r in payload["results"]] == [9.0, 4.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["abc", ["ok", ""]])
async def test_malformed_selection_is_a_400_and_searches_nothing(env, value):
    status, payload = await _call(env, datasets=value)

    assert status == 400
    assert "datasets" in payload["error"] or "dataset" in payload["error"]
    assert env.doc_calls == []


@pytest.mark.asyncio
async def test_explicit_null_datasets_selects_all_visible_over_saved_and_inline(env):
    env.saved_filters = {"datasets": ["c"]}

    await _call(env, datasets=None, filter_id="f", filters={"datasets": ["b"]})

    assert _searched(env) == [["a", "b", "c"]]


@pytest.mark.asyncio
async def test_omitted_datasets_still_falls_through_to_saved_filter(env):
    env.saved_filters = {"datasets": ["c"]}

    await _call(env, filter_id="f")

    assert _searched(env) == [["c"]]
