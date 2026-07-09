"""
Unit tests for the embedding field helpers.

Focuses on ``build_knn_vector_field``, the single source of truth for
OpenRAG's ``knn_vector`` field mapping. Callers across ``config.settings``,
``utils.embeddings``, ``utils.embedding_fields``, and
``scripts.migrate_embedding_model_field`` rely on it producing a consistent
JVector/DiskANN method configuration with only the dimension varying per
embedding model.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from utils.embedding_fields import (
    build_embedding_space_aggregation,
    build_knn_vector_field,
    embedding_space_after_keys,
    embedding_spaces_from_aggregation,
    get_embedding_field_name,
    get_embedding_space_id,
    normalize_model_name,
    split_embedding_space_id,
)


def test_embedding_space_identity_qualifies_model_with_exact_provider() -> None:
    space_id = get_embedding_space_id("Azure", "text-embedding-3-small")

    assert space_id == "azure:text-embedding-3-small"
    assert split_embedding_space_id(space_id) == ("azure", "text-embedding-3-small")
    assert get_embedding_field_name(space_id) == "chunk_embedding_azure_text_embedding_3_small"
    assert get_embedding_field_name("text-embedding-3-small") == (
        "chunk_embedding_text_embedding_3_small"
    )


def test_embedding_space_aggregation_preserves_exact_and_legacy_routes() -> None:
    aggregation = build_embedding_space_aggregation(size=10)

    assert aggregation["embedding_spaces"]["composite"]["sources"] == [
        {"space_id": {"terms": {"field": "embedding_space_id"}}}
    ]
    assert aggregation["legacy_embedding_models"]["composite"]["sources"] == [
        {"model": {"terms": {"field": "embedding_model"}}}
    ]

    result = {
        "aggregations": {
            "embedding_spaces": {
                "buckets": [{"key": {"space_id": "azure:text-embedding-3-small"}, "doc_count": 2}],
                "after_key": {"space_id": "azure:text-embedding-3-small"},
            },
            "legacy_embedding_models": {
                "buckets": [{"key": {"model": "text-embedding-3-small"}, "doc_count": 3}],
                "after_key": {"model": "text-embedding-3-small"},
            },
        }
    }
    spaces = embedding_spaces_from_aggregation(result)

    assert [space.route_model for space in spaces] == [
        "space:azure:text-embedding-3-small",
        "legacy:text-embedding-3-small",
    ]
    assert [space.field_identity for space in spaces] == [
        "azure:text-embedding-3-small",
        "text-embedding-3-small",
    ]
    assert embedding_space_after_keys(result) == (
        {"space_id": "azure:text-embedding-3-small"},
        {"model": "text-embedding-3-small"},
    )


def test_embedding_space_aggregation_ignores_missing_bucket_keys() -> None:
    result = {
        "aggregations": {
            "embedding_spaces": {"buckets": [{"key": {}}, {"key": None}]},
            "legacy_embedding_models": {"buckets": [{"key": {}}, {"key": None}]},
        }
    }

    assert embedding_spaces_from_aggregation(result) == []


class TestBuildKnnVectorFieldStructure:
    """Shape of the returned mapping dict."""

    def test_returns_dict(self) -> None:
        result = build_knn_vector_field(1536)
        assert isinstance(result, dict)

    def test_top_level_keys(self) -> None:
        result = build_knn_vector_field(1536)
        assert set(result.keys()) == {"type", "dimension", "method"}

    def test_type_is_knn_vector(self) -> None:
        assert build_knn_vector_field(1536)["type"] == "knn_vector"

    def test_method_name_is_disk_ann(self) -> None:
        assert build_knn_vector_field(1536)["method"]["name"] == "disk_ann"

    def test_method_engine_is_jvector(self) -> None:
        assert build_knn_vector_field(1536)["method"]["engine"] == "jvector"

    def test_method_space_type_is_l2(self) -> None:
        assert build_knn_vector_field(1536)["method"]["space_type"] == "l2"

    def test_method_parameters_keys(self) -> None:
        params = build_knn_vector_field(1536)["method"]["parameters"]
        assert set(params.keys()) == {"ef_construction", "m"}


class TestBuildKnnVectorFieldDimensionPropagation:
    """Dimension should be the only value that varies between calls."""

    @pytest.mark.parametrize("dimension", [384, 768, 1024, 1536, 3072])
    def test_dimension_propagates(self, dimension: int) -> None:
        assert build_knn_vector_field(dimension)["dimension"] == dimension

    def test_method_block_identical_across_dimensions(self) -> None:
        small = build_knn_vector_field(384)
        large = build_knn_vector_field(3072)
        assert small["method"] == large["method"]


class TestBuildKnnVectorFieldSettingsResolution:
    """The helper must read KNN_M and KNN_EF_CONSTRUCTION from config.settings."""

    def test_matches_current_settings(self) -> None:
        from config import settings

        params = build_knn_vector_field(1536)["method"]["parameters"]
        assert params["m"] == settings.KNN_M
        assert params["ef_construction"] == settings.KNN_EF_CONSTRUCTION

    def test_picks_up_settings_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("config.settings.KNN_M", 32)
        monkeypatch.setattr("config.settings.KNN_EF_CONSTRUCTION", 200)

        params = build_knn_vector_field(1536)["method"]["parameters"]
        assert params["m"] == 32
        assert params["ef_construction"] == 200


class TestBuildKnnVectorFieldIsolation:
    """Each call must return a fresh dict so callers can mutate safely."""

    def test_returns_new_dict_each_call(self) -> None:
        first = build_knn_vector_field(1536)
        second = build_knn_vector_field(1536)
        assert first is not second
        assert first["method"] is not second["method"]
        assert first["method"]["parameters"] is not second["method"]["parameters"]

    def test_mutation_does_not_leak(self) -> None:
        first = build_knn_vector_field(1536)
        first["method"]["parameters"]["advanced.hierarchy_enabled"] = True

        second = build_knn_vector_field(1536)
        assert "advanced.hierarchy_enabled" not in second["method"]["parameters"]


class TestNormalizeModelNameOci:
    """OCI's Cohere embed model names must normalize to safe, distinct
    OpenSearch field-name suffixes -- specifically checked against
    ``cohere.embed-multilingual-v3.0``, the model this integration targets.
    """

    def test_oci_cohere_multilingual_v3_model_name(self) -> None:
        assert (
            normalize_model_name("cohere.embed-multilingual-v3.0")
            == "cohere_embed_multilingual_v3_0"
        )

    def test_oci_prefixed_variant_normalizes_consistently(self) -> None:
        # get_litellm_model_name() prefixes with "oci/"; the embedding_model
        # field stored on each chunk uses the *bare* model name today (see
        # models.processors), so both forms should normalize distinctly and
        # predictably rather than colliding or erroring.
        bare = normalize_model_name("cohere.embed-multilingual-v3.0")
        prefixed = normalize_model_name("oci/cohere.embed-multilingual-v3.0")
        assert bare == "cohere_embed_multilingual_v3_0"
        assert prefixed == "oci_cohere_embed_multilingual_v3_0"
        assert bare != prefixed

    def test_distinct_from_sibling_cohere_variant(self) -> None:
        # A hypothetical Bedrock-style Cohere model name without the ".0"
        # patch suffix must not collide with the OCI ".0" variant.
        multilingual_v3_0 = normalize_model_name("cohere.embed-multilingual-v3.0")
        multilingual_v3 = normalize_model_name("cohere.embed-multilingual-v3")
        assert multilingual_v3_0 != multilingual_v3
        assert multilingual_v3_0 == "cohere_embed_multilingual_v3_0"
        assert multilingual_v3 == "cohere_embed_multilingual_v3"

    def test_distinct_from_english_variant(self) -> None:
        multilingual = normalize_model_name("cohere.embed-multilingual-v3.0")
        english = normalize_model_name("cohere.embed-english-v3.0")
        assert multilingual != english

    def test_embed_field_name_for_oci_model(self) -> None:
        assert (
            get_embedding_field_name("cohere.embed-multilingual-v3.0")
            == "chunk_embedding_cohere_embed_multilingual_v3_0"
        )


class TestBuildKnnVectorFieldCallSitesMatch:
    """Ensure every caller produces the same shape the helper promises."""

    def test_index_body_uses_helper_output(self) -> None:
        from config.settings import INDEX_BODY, VECTOR_DIM

        chunk_field: dict[str, Any] = INDEX_BODY["mappings"]["properties"]["chunk_embedding"]
        expected = build_knn_vector_field(VECTOR_DIM)
        assert chunk_field == expected

    @pytest.mark.asyncio
    async def test_create_index_body_precreates_configured_embedding_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: SimpleNamespace(
                knowledge=SimpleNamespace(embedding_model="text-embedding-3-large")
            ),
        )

        from utils.embeddings import create_index_body

        body = await create_index_body("text-embedding-3-large", 3072)
        properties = body["mappings"]["properties"]
        embedding_field = get_embedding_field_name("text-embedding-3-large")

        assert properties[embedding_field] == build_knn_vector_field(3072)
        assert properties["owner_email"] == {"type": "keyword"}

    @pytest.mark.asyncio
    async def test_create_index_body_uses_configured_shards_and_replicas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("config.settings.OPENSEARCH_NUMBER_OF_SHARDS", 3)
        monkeypatch.setattr("config.settings.OPENSEARCH_NUMBER_OF_REPLICAS", 2)

        from utils.embeddings import create_index_body

        body = await create_index_body("text-embedding-3-small", 1536)

        assert body["settings"]["number_of_shards"] == 3
        assert body["settings"]["number_of_replicas"] == 2

    @pytest.mark.asyncio
    async def test_create_index_body_uses_provider_qualified_vector_field(self) -> None:
        from utils.embeddings import create_index_body

        body = await create_index_body(
            "text-embedding-3-small",
            1536,
            embedding_provider="azure",
            embedding_space_id="azure:text-embedding-3-small",
        )
        properties = body["mappings"]["properties"]

        assert "chunk_embedding_azure_text_embedding_3_small" in properties
        assert properties["embedding_provider"] == {"type": "keyword"}
        assert properties["embedding_space_id"] == {"type": "keyword"}
