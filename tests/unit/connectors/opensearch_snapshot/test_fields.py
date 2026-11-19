from __future__ import annotations

import pytest

from connectors.opensearch_snapshot import fields as f
from connectors.opensearch_snapshot.fields import FieldInfo
from connectors.opensearch_snapshot.metadata import decode_index_metadata

from ._fakes import FIXTURES

MAPPING = {
    "properties": {
        "title": {
            "type": "text",
            "fields": {"keyword": {"type": "keyword"}, "raw": {"type": "text"}},
        },
        "body": {"type": "text"},
        "summary": {"type": "match_only_text"},
        "url": {"type": "keyword"},
        "meta": {
            "properties": {
                "author": {"type": "keyword"},
                "tags": {"type": "keyword"},
                "inner": {"properties": {"note": {"type": "text"}}},
            }
        },
        "comments": {"type": "nested", "properties": {"text": {"type": "text"}}},
        "year": {"type": "integer"},
        "embedding": {
            "type": "knn_vector",
            "dimension": 384,
            "method": {"engine": "lucene", "name": "hnsw"},
        },
        "emb2": {"type": "dense_vector", "dims": 768},
        "emb3": {"type": "knn_vector", "model_id": "abc"},
        "weird": "not-a-dict",
        "untyped": {},
    }
}


def names(infos):
    return [i.name for i in infos]


def test_flatten_mapping_uses_source_paths_and_excludes_multi_fields():
    fields = f.flatten_mapping(MAPPING)
    assert names(fields) == [
        "body",
        "emb2",
        "emb3",
        "embedding",
        "meta.author",
        "meta.inner.note",
        "meta.tags",
        "summary",
        "title",
        "url",
        "year",
    ]
    assert "title.keyword" not in names(fields) and "title.raw" not in names(fields)
    by = {i.name: i for i in fields}
    assert by["embedding"] == FieldInfo("embedding", "knn_vector", 384, "lucene")
    assert by["emb2"] == FieldInfo("emb2", "dense_vector", 768, None)
    assert by["emb3"].dims is None


def test_flatten_accepts_wrapped_and_empty_mappings():
    assert names(f.flatten_mapping({"_doc": MAPPING})) == names(f.flatten_mapping(MAPPING))
    assert f.flatten_mapping({}) == []
    assert f.flatten_mapping(None) == []
    assert f.flatten_mapping({"dynamic": "strict"}) == []


def test_flatten_real_fixture_mapping():
    info = decode_index_metadata((FIXTURES / "scientific_discoveries_meta.dat").read_bytes())
    fields = {i.name: i.type for i in f.flatten_mapping(info.mappings)}
    assert fields == {
        "description": "text",
        "field": "keyword",
        "scientist": "keyword",
        "title": "text",
        "year": "integer",
    }
    bio = decode_index_metadata((FIXTURES / "famous_scientists_meta.dat").read_bytes())
    assert "biography" in {i.name for i in f.flatten_mapping(bio.mappings)}


def test_to_dict_includes_engine_only_for_vectors():
    assert FieldInfo("t", "text").to_dict() == {"name": "t", "type": "text", "dims": None}
    assert FieldInfo("v", "knn_vector", 3, "faiss").to_dict() == {
        "name": "v",
        "type": "knn_vector",
        "dims": 3,
        "engine": "faiss",
    }


def test_vector_fields():
    assert names(f.vector_fields(f.flatten_mapping(MAPPING))) == ["emb2", "emb3", "embedding"]


# ------------------------------------------------------------------ suggest / validate


SAMPLES = [
    {
        "title": "Photo 51",
        "body": "x" * 500,
        "summary": "short",
        "url": "https://example.com/a",
        "meta": {"inner": {"note": "n" * 50}},
    },
    {"title": "Other", "body": "y" * 300, "summary": "tiny", "url": "https://example.com/b"},
]


def test_suggest_field_map_orders_by_sample_length_and_finds_title_and_url():
    suggestion = f.suggest_field_map(f.flatten_mapping(MAPPING), SAMPLES)
    assert suggestion["text_fields"] == ["body", "meta.inner.note", "title", "summary"]
    assert suggestion["title_field"] == "title"
    assert suggestion["url_field"] == "url"
    assert f.validate_field_map(suggestion, f.flatten_mapping(MAPPING)) == []


def test_nested_mappings_are_neither_discovered_nor_valid_but_object_paths_are():
    fields = f.flatten_mapping(MAPPING)
    assert not [n for n in names(fields) if n.startswith("comments")]  # nested subtree excluded
    assert "meta.inner.note" in names(fields)  # plain object paths stay
    deep = {
        "properties": {
            "outer": {
                "type": "nested",
                "properties": {
                    "obj": {"properties": {"text": {"type": "text"}}},
                    "inner": {"type": "nested", "properties": {"x": {"type": "keyword"}}},
                },
            },
            "ok": {"type": "text"},
        }
    }
    assert names(f.flatten_mapping(deep)) == ["ok"]
    errors = f.validate_field_map({"text_fields": ["comments.text"]}, fields)
    assert errors and "nested" in errors[0] and "comments.text" in errors[0]
    errors = f.validate_field_map(
        {"text_fields": ["body"], "title_field": "outer.obj.text"}, f.flatten_mapping(deep)
    )
    assert errors and "nested mappings are not supported" in errors[0]


def test_suggest_falls_back_to_keywords_and_detects_url_from_samples():
    fields = f.flatten_mapping(
        {"properties": {"label": {"type": "keyword"}, "homepage": {"type": "keyword"}}}
    )
    suggestion = f.suggest_field_map(fields, [{"label": "a", "homepage": "https://x.org"}])
    assert suggestion == {"text_fields": ["label"], "title_field": None, "url_field": "homepage"}
    assert f.suggest_field_map([], []) == {
        "text_fields": [],
        "title_field": None,
        "url_field": None,
    }


def test_suggest_real_fixture():
    info = decode_index_metadata((FIXTURES / "scientific_discoveries_meta.dat").read_bytes())
    suggestion = f.suggest_field_map(
        f.flatten_mapping(info.mappings),
        [{"title": "Photo 51", "description": "X-ray diffraction image of DNA"}],
    )
    assert suggestion["text_fields"][0] == "description" and suggestion["title_field"] == "title"


def test_validate_field_map_accepts_valid_maps():
    fields = f.flatten_mapping(MAPPING)
    assert (
        f.validate_field_map(
            {"text_fields": ["body", "title"], "title_field": "title", "url_field": None}, fields
        )
        == []
    )
    assert f.validate_field_map({"text_fields": ["body"]}, fields) == []


def _map(**over):
    return {"text_fields": ["body"], **over}


@pytest.mark.parametrize(
    ("field_map", "needle"),
    [
        ("not a dict", "must be an object"),
        (None, "must be an object"),
        (_map(text_fields=[]), "at least one"),
        (_map(text_fields="body"), "at least one"),
        (_map(text_fields=["title.keyword"]), "source field path"),
        (_map(text_fields=["nope"]), "not a field"),
        (_map(text_fields=["year"]), "text or keyword"),
        (_map(text_fields=["body", "body"]), "duplicates"),
        (_map(text_fields=[f"body{i}" for i in range(11)]), "at most"),
        (_map(text_fields=[5]), "field name"),
        (_map(title_field="year"), "text or keyword"),
        (_map(title_field="ghost"), "not a field"),
        (_map(url_field=""), "field name"),
        (_map(extra=1), "unknown field_map keys"),
    ],
)
def test_validate_field_map_messages(field_map, needle):
    errors = f.validate_field_map(field_map, f.flatten_mapping(MAPPING))
    assert any(needle in e for e in errors), errors


# ------------------------------------------------------------------ retrieval


MODELS = {"openai:text-embedding-3-small", "ollama:nomic-embed-text"}
VEC_FIELDS = f.flatten_mapping(MAPPING)


def hybrid(**over):
    base = {
        "mode": "hybrid",
        "vector_field": "embedding",
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dims": 384,
    }
    base.update(over)
    return base


def test_default_and_lexical_retrieval():
    assert f.default_retrieval() == {"mode": "lexical"}
    assert f.validate_retrieval({"mode": "lexical"}, VEC_FIELDS, set()) == []
    assert f.validate_retrieval({"mode": "lexical", "dims": 9}, VEC_FIELDS, set()) == []


def test_hybrid_retrieval_valid():
    assert f.validate_retrieval(hybrid(), VEC_FIELDS, MODELS) == []
    # vector field without a discoverable dimension takes the caller's dims
    assert f.validate_retrieval(hybrid(vector_field="emb3", dims=1536), VEC_FIELDS, MODELS) == []


@pytest.mark.parametrize(
    ("retrieval", "needle"),
    [
        ("lexical", "must be an object"),
        ({}, "mode must be"),
        ({"mode": "semantic"}, "mode must be"),
        (hybrid(vector_field="title"), "knn_vector or dense_vector"),  # text field is not a vector
        (hybrid(vector_field="ghost"), "knn_vector or dense_vector"),
        (hybrid(vector_field=None), "knn_vector or dense_vector"),
        (hybrid(provider=""), "provider and model"),
        (hybrid(model=None), "provider and model"),
        (hybrid(provider="anthropic"), "not available"),
        (hybrid(model="other"), "not available"),
        (hybrid(dims=None), "dimension"),
        (hybrid(dims=0), "dimension"),
        (hybrid(dims=True), "dimension"),
        (hybrid(dims=768), "does not match"),
        (hybrid(extra=1), "unknown retrieval keys"),
    ],
)
def test_hybrid_retrieval_invalid(retrieval, needle):
    errors = f.validate_retrieval(retrieval, VEC_FIELDS, MODELS)
    assert any(needle in e for e in errors), errors
