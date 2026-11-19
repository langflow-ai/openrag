import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

import auth_context
from services import dataset_search_service as dss
from services.dataset_search_service import DatasetSearchService, resolve_datasets, rrf_merge


@dataclass(frozen=True)
class Record:
    """Same fields as connectors.opensearch_snapshot.service.DatasetRecord."""

    id: str
    index_alias: str
    display_name: str = "Scientists"
    import_name: str = "Scientists v1"
    import_id: str = "imp-1"
    slug: str = "abcdefghij"
    ordinal: int = 0
    source_index: str = "famous_scientists"
    description: str = ""
    field_map: dict = field(
        default_factory=lambda: {
            "text_fields": ["bio", "meta.notes"],
            "title_field": "name",
            "url_field": "link",
        }
    )
    retrieval: dict = field(default_factory=lambda: {"mode": "lexical"})
    shared: bool = False
    owner_user_id: str = "owner"


class StatusError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class FakeClient:
    def __init__(self, responses: dict[str, Any]):
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def search(self, *, index, body):
        self.calls.append({"index": index, "body": body})
        outcome = self.responses[index]
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return await outcome()
        return outcome


class FakeSessionManager:
    def __init__(self, client):
        self.client = client
        self.requests: list[tuple[Any, Any]] = []

    def get_user_opensearch_client(self, user_id, jwt_token=None):
        self.requests.append((user_id, jwt_token))
        return self.client


def hit(doc_id, score=1.0, **source):
    return {"_id": doc_id, "_score": score, "_source": source}


def response(*hits):
    return {"hits": {"hits": list(hits)}}


@pytest.fixture
def visible(monkeypatch):
    records: list[Record] = []

    async def list_visible(user_id):
        list_visible.user_ids.append(user_id)
        return list(records)

    list_visible.user_ids = []
    monkeypatch.setattr(dss, "list_visible_datasets", list_visible)
    list_visible.records = records
    return list_visible


def _service(client):
    manager = FakeSessionManager(client)
    return DatasetSearchService(manager), manager


@pytest.mark.asyncio
async def test_lexical_result_has_the_documented_shape(visible):
    visible.records.append(Record(id="d1", index_alias="ds_abcdefghij_0"))
    client = FakeClient(
        {
            "ds_abcdefghij_0": {
                "hits": {
                    "hits": [
                        {
                            "_id": "doc/1",
                            "_score": 2.5,
                            "_source": {
                                "bio": "Photo 51 showed the helix",
                                "meta": {"notes": "x-ray"},
                                "name": "Rosalind Franklin",
                                "link": "https://example.test/rf",
                            },
                            "highlight": {"bio": ["<mark>helix</mark>"]},
                        }
                    ]
                }
            }
        }
    )
    service, manager = _service(client)

    out = await service.search("helix", user_id="u1", jwt_token="jwt", dataset_ids=["d1"])

    assert out["errors"] == []
    (result,) = out["results"]
    assert result["chunk_id"] == result["id"]
    assert result["chunk_id"].startswith("ds-d1-")
    assert result["text"] == "Photo 51 showed the helix x-ray"
    assert result["filename"] == "Scientists / Rosalind Franklin"
    assert result["source_url"] == "https://example.test/rf"
    assert result["highlights"] == ["<mark>helix</mark>"]
    assert result["page"] is None
    assert result["mimetype"] == "application/x-opensearch-document"
    assert result["connector_type"] == "opensearch_snapshot"
    assert result["document_id"] == "ds_abcdefghij_0/doc/1"
    assert result["dataset"] == {
        "id": "d1",
        "name": "Scientists",
        "import_name": "Scientists v1",
        "source_index": "famous_scientists",
    }
    assert manager.requests == [("u1", "jwt")]
    body = client.calls[0]["body"]
    assert body["query"] == {
        "multi_match": {
            "query": "helix",
            "fields": ["bio", "meta.notes", "name^1.5"],
            "type": "best_fields",
        }
    }
    assert set(body["highlight"]["fields"]) == {"bio", "meta.notes"}
    assert "encoder" not in body["highlight"]


@pytest.mark.asyncio
async def test_missing_title_and_url_fall_back_to_id_and_opaque_url(visible):
    visible.records.append(Record(id="d1", index_alias="ds_x_0"))
    client = FakeClient({"ds_x_0": response(hit("abc", bio="text"))})

    out = await _service(client)[0].search("q", user_id="u", jwt_token=None, dataset_ids=["d1"])

    (result,) = out["results"]
    assert result["filename"] == "Scientists / abc"
    assert result["source_url"] == "opensearch://ds_x_0/abc"


@pytest.mark.asyncio
async def test_text_is_capped(visible):
    visible.records.append(Record(id="d1", index_alias="ds_x_0"))
    client = FakeClient({"ds_x_0": response(hit("a", bio="x" * 9000))})

    out = await _service(client)[0].search("q", user_id="u", jwt_token=None, dataset_ids=["d1"])

    assert len(out["results"][0]["text"]) == 4000


@pytest.mark.asyncio
async def test_chunk_ids_are_stable_and_unique_for_duplicate_titles(visible):
    visible.records.extend(
        [Record(id="d1", index_alias="ds_x_0"), Record(id="d2", index_alias="ds_x_1")]
    )
    shared_title = {"bio": "same", "name": "Duplicate title"}
    client = FakeClient(
        {
            "ds_x_0": response(hit("1", **shared_title), hit("2", **shared_title)),
            "ds_x_1": response(hit("1", **shared_title)),
        }
    )
    service, _ = _service(client)

    first = await service.search("q", user_id="u", jwt_token=None, dataset_ids=["d1", "d2"])
    second = await service.search("q", user_id="u", jwt_token=None, dataset_ids=["d1", "d2"])

    ids = [r["chunk_id"] for r in first["results"]]
    assert len(ids) == 3
    assert len(set(ids)) == 3
    assert sorted(ids) == sorted(r["chunk_id"] for r in second["results"])
    assert all(r["filename"].endswith("Duplicate title") for r in first["results"])


@pytest.mark.asyncio
async def test_ids_with_unsafe_characters_encode_to_url_safe_chunk_ids(visible):
    visible.records.append(Record(id="d1", index_alias="ds_x_0"))
    client = FakeClient({"ds_x_0": response(hit("a/b c?é=", bio="t"))})

    out = await _service(client)[0].search("q", user_id="u", jwt_token=None, dataset_ids=["d1"])

    suffix = out["results"][0]["chunk_id"].removeprefix("ds-d1-")
    assert suffix and all(c.isalnum() or c in "-_" for c in suffix)


@pytest.mark.asyncio
async def test_a_403_on_one_dataset_only_drops_that_dataset(visible):
    visible.records.extend(
        [Record(id="d1", index_alias="ds_x_0"), Record(id="d2", index_alias="ds_x_1")]
    )
    client = FakeClient({"ds_x_0": StatusError(403), "ds_x_1": response(hit("ok", bio="fine"))})

    out = await _service(client)[0].search(
        "q", user_id="u", jwt_token=None, dataset_ids=["d1", "d2"]
    )

    assert [r["dataset"]["id"] for r in out["results"]] == ["d2"]
    assert out["errors"] == [{"dataset_id": "d1", "code": "forbidden"}]


@pytest.mark.asyncio
async def test_other_failures_and_timeouts_are_isolated_with_codes(visible):
    visible.records.extend(
        [
            Record(id="d1", index_alias="ds_x_0"),
            Record(id="d2", index_alias="ds_x_1"),
            Record(id="d3", index_alias="ds_x_2"),
        ]
    )

    async def slow():
        await asyncio.sleep(5)

    client = FakeClient(
        {"ds_x_0": StatusError(404), "ds_x_1": slow, "ds_x_2": RuntimeError("boom")}
    )

    out = await _service(client)[0].search(
        "q", user_id="u", jwt_token=None, dataset_ids=["d1", "d2", "d3"], timeout_s=0.05
    )

    assert out["results"] == []
    assert sorted((e["dataset_id"], e["code"]) for e in out["errors"]) == [
        ("d1", "not_found"),
        ("d2", "timeout"),
        ("d3", "search_failed"),
    ]


@pytest.mark.asyncio
async def test_error_codes_never_carry_exception_text(visible):
    visible.records.append(Record(id="d1", index_alias="ds_x_0"))
    client = FakeClient({"ds_x_0": RuntimeError("secret token abc")})

    out = await _service(client)[0].search("q", user_id="u", jwt_token=None, dataset_ids=["d1"])

    assert "secret" not in repr(out)


@pytest.mark.asyncio
async def test_only_visible_datasets_are_searched(visible):
    visible.records.append(Record(id="d1", index_alias="ds_x_0"))
    client = FakeClient({"ds_x_0": response(), "ds_other_0": response(hit("leak", bio="no"))})

    out = await _service(client)[0].search(
        "q", user_id="u", jwt_token=None, dataset_ids=["d1", "not-mine"]
    )

    assert [c["index"] for c in client.calls] == ["ds_x_0"]
    assert out["results"] == []
    assert visible.user_ids == ["u"]


@pytest.mark.asyncio
@pytest.mark.parametrize("dataset_ids,query", [([], "q"), (["d1"], "   ")])
async def test_nothing_to_search_makes_no_requests(visible, dataset_ids, query):
    visible.records.append(Record(id="d1", index_alias="ds_x_0"))
    client = FakeClient({})
    service, manager = _service(client)

    out = await service.search(query, user_id="u", jwt_token=None, dataset_ids=dataset_ids)

    assert out == {"results": [], "errors": []}
    assert client.calls == [] and manager.requests == []


HYBRID = {
    "mode": "hybrid",
    "vector_field": "embedding",
    "provider": "ollama",
    "model": "embed-small",
    "dims": 3,
}


def _embeddings(monkeypatch, vector=None, error=None):
    calls: list[tuple[dict, bool]] = []

    async def embeddings(body, *, config=None, interactive=False):
        calls.append((dict(body), interactive))
        if error:
            raise error
        return {"data": [{"embedding": vector}]}

    monkeypatch.setattr(dss.llm_gateway, "embeddings", embeddings)
    return calls


@pytest.mark.asyncio
async def test_hybrid_adds_knn_with_an_interactive_qualified_embedding(visible, monkeypatch):
    visible.records.append(Record(id="d1", index_alias="ds_x_0", retrieval=HYBRID))
    calls = _embeddings(monkeypatch, vector=[0.1, 0.2, 0.3])
    client = FakeClient({"ds_x_0": response(hit("a", bio="t"))})

    out = await _service(client)[0].search("q", user_id="u", jwt_token=None, dataset_ids=["d1"])

    assert out["errors"] == []
    assert calls == [({"model": "ollama:embed-small", "input": ["q"]}, True)]
    should = client.calls[0]["body"]["query"]["bool"]["should"]
    assert "multi_match" in should[0]
    assert should[1] == {"knn": {"embedding": {"vector": [0.1, 0.2, 0.3], "k": 5}}}


@pytest.mark.asyncio
async def test_hybrid_dims_mismatch_skips_the_vector_part_and_reports_it(visible, monkeypatch):
    visible.records.append(Record(id="d1", index_alias="ds_x_0", retrieval=HYBRID))
    _embeddings(monkeypatch, vector=[0.1, 0.2])
    client = FakeClient({"ds_x_0": response(hit("a", bio="t"))})

    out = await _service(client)[0].search("q", user_id="u", jwt_token=None, dataset_ids=["d1"])

    assert "bool" not in client.calls[0]["body"]["query"]
    assert "multi_match" in client.calls[0]["body"]["query"]
    assert len(out["results"]) == 1
    assert out["errors"] == [{"dataset_id": "d1", "code": "embedding_dims_mismatch"}]


@pytest.mark.asyncio
async def test_hybrid_embedding_failure_keeps_lexical_results(visible, monkeypatch):
    visible.records.append(Record(id="d1", index_alias="ds_x_0", retrieval=HYBRID))
    _embeddings(monkeypatch, error=RuntimeError("provider down"))
    client = FakeClient({"ds_x_0": response(hit("a", bio="t"))})

    out = await _service(client)[0].search("q", user_id="u", jwt_token=None, dataset_ids=["d1"])

    assert len(out["results"]) == 1
    assert out["errors"] == [{"dataset_id": "d1", "code": "embedding_failed"}]


@pytest.mark.asyncio
async def test_one_embedding_serves_datasets_sharing_a_model(visible, monkeypatch):
    visible.records.extend(
        [
            Record(id="d1", index_alias="ds_x_0", retrieval=HYBRID),
            Record(id="d2", index_alias="ds_x_1", retrieval=HYBRID),
            Record(id="d3", index_alias="ds_x_2"),
        ]
    )
    calls = _embeddings(monkeypatch, vector=[1.0, 2.0, 3.0])
    client = FakeClient({a: response() for a in ("ds_x_0", "ds_x_1", "ds_x_2")})

    await _service(client)[0].search(
        "q", user_id="u", jwt_token=None, dataset_ids=["d1", "d2", "d3"]
    )

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_lexical_only_datasets_never_embed(visible, monkeypatch):
    visible.records.append(Record(id="d1", index_alias="ds_x_0"))
    calls = _embeddings(monkeypatch, vector=[1.0])
    client = FakeClient({"ds_x_0": response()})

    await _service(client)[0].search("q", user_id="u", jwt_token=None, dataset_ids=["d1"])

    assert calls == []


@pytest.mark.asyncio
async def test_dataset_without_text_fields_reports_invalid_field_map(visible):
    visible.records.append(Record(id="d1", index_alias="ds_x_0", field_map={}))
    client = FakeClient({})

    out = await _service(client)[0].search("q", user_id="u", jwt_token=None, dataset_ids=["d1"])

    assert client.calls == []
    assert out["errors"] == [{"dataset_id": "d1", "code": "invalid_field_map"}]


@pytest.mark.asyncio
async def test_each_dataset_search_is_traced(visible, monkeypatch):
    seen: list[tuple[str, dict]] = []

    class _Span:
        def set(self, **attributes):
            seen.append(("set", attributes))

    @contextmanager
    def fake_trace_span(name, **attributes):
        seen.append((name, attributes))
        yield _Span()

    monkeypatch.setattr(dss, "trace_span", fake_trace_span)
    visible.records.append(Record(id="d1", index_alias="ds_x_0"))
    client = FakeClient({"ds_x_0": response(hit("a", bio="t"))})

    await _service(client)[0].search("q", user_id="u", jwt_token=None, dataset_ids=["d1"])

    assert seen[0] == ("search.dataset", {"dataset_id": "d1"})
    assert seen[1][1]["hits"] == 1
    assert "latency_ms" in seen[1][1]


def test_rrf_merge_ranks_by_fused_reciprocal_rank_and_dedupes():
    a = [{"chunk_id": "x"}, {"chunk_id": "y"}]
    b = [{"chunk_id": "y"}, {"chunk_id": "z"}]

    merged = rrf_merge([a, b], k=60, limit=10)

    assert [r["chunk_id"] for r in merged] == ["y", "x", "z"]
    assert merged[0]["score"] == pytest.approx(1 / 61 + 1 / 62)
    assert a == [{"chunk_id": "x"}, {"chunk_id": "y"}]


def test_rrf_merge_applies_limit():
    merged = rrf_merge([[{"chunk_id": str(i)} for i in range(10)]], limit=3)
    assert [r["chunk_id"] for r in merged] == ["0", "1", "2"]


# --- resolve_datasets: who may search what -----------------------------------------


@pytest.fixture
def feature(monkeypatch):
    state = {"on": True}
    monkeypatch.setattr(dss, "snapshot_import_available", lambda: state["on"])
    return state


@pytest.fixture
def auth():
    auth_context.set_auth_context("auth-user", "jwt")
    yield
    auth_context.set_auth_context(None, None)


@pytest.mark.asyncio
async def test_resolve_uses_the_auth_context_identity(visible, feature, auth):
    visible.records.extend([Record(id="a", index_alias="x"), Record(id="b", index_alias="y")])

    got = await resolve_datasets(None)

    assert [r.id for r in got] == ["a", "b"]
    assert visible.user_ids == ["auth-user"]


@pytest.mark.asyncio
async def test_resolve_applies_selection_and_tool_narrowing(visible, feature, auth):
    visible.records.extend([Record(id=i, index_alias=i) for i in "abc"])

    assert [r.id for r in await resolve_datasets(["a", "b", "zzz"])] == ["a", "b"]
    assert [r.id for r in await resolve_datasets(["a", "b"], ["b", "c"])] == ["b"]


@pytest.mark.asyncio
async def test_resolve_empty_selection_never_looks_anything_up(visible, feature, auth):
    visible.records.append(Record(id="a", index_alias="x"))

    assert await resolve_datasets([]) == []
    assert visible.user_ids == []


@pytest.mark.asyncio
async def test_resolve_is_empty_when_the_feature_is_unavailable(visible, feature, auth):
    visible.records.append(Record(id="a", index_alias="x"))
    feature["on"] = False

    assert await resolve_datasets(None) == []
    assert visible.user_ids == []


@pytest.mark.asyncio
async def test_resolve_is_empty_without_an_authenticated_user(visible, feature):
    auth_context.set_auth_context(None, None)
    visible.records.append(Record(id="a", index_alias="x"))

    assert await resolve_datasets(None) == []
    assert visible.user_ids == []


@pytest.mark.asyncio
async def test_object_arrays_are_traversed_and_special_characters_stay_raw(visible):
    visible.records.append(
        Record(
            id="d1",
            index_alias="ds_x_0",
            field_map={"text_fields": ["sections.text"], "title_field": "sections.title"},
        )
    )
    client = FakeClient(
        {
            "ds_x_0": {
                "hits": {
                    "hits": [
                        {
                            "_id": "a",
                            "_source": {
                                "sections": [
                                    {"text": "R&D <b>", "title": "T"},
                                    {"other": 1},
                                    {"text": "Photo 51"},
                                ]
                            },
                            "highlight": {"sections.text": ["<mark>R&D</mark> <b>"]},
                        }
                    ]
                }
            }
        }
    )

    out = await _service(client)[0].search("q", user_id="u", jwt_token=None, dataset_ids=["d1"])

    (result,) = out["results"]
    assert result["text"] == "R&D <b> Photo 51"
    assert result["filename"] == "Scientists / T"
    assert result["highlights"] == ["<mark>R&D</mark> <b>"]


@pytest.mark.asyncio
async def test_fields_under_nested_paths_are_never_queried(visible):
    visible.records.append(
        Record(
            id="d1",
            index_alias="ds_x_0",
            field_map={
                "text_fields": ["bio", "comments.text"],
                "title_field": "comments.author",
                "nested_paths": ["comments"],
            },
        )
    )
    client = FakeClient({"ds_x_0": response()})

    await _service(client)[0].search("q", user_id="u", jwt_token=None, dataset_ids=["d1"])

    body = client.calls[0]["body"]
    assert body["query"]["multi_match"]["fields"] == ["bio"]
    assert set(body["highlight"]["fields"]) == {"bio"}
