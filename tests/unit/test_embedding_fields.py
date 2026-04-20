"""
Unit tests for the embedding field helpers.

Focuses on ``build_knn_vector_field``, the single source of truth for
OpenRAG's ``knn_vector`` field mapping. Callers across ``config.settings``,
``utils.embeddings``, ``utils.embedding_fields``, and
``scripts.migrate_embedding_model_field`` rely on it producing a consistent
JVector/DiskANN method configuration with only the dimension varying per
embedding model.
"""
from typing import Any, Dict

import pytest

from utils.embedding_fields import build_knn_vector_field


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


class TestBuildKnnVectorFieldCallSitesMatch:
    """Ensure every caller produces the same shape the helper promises."""

    def test_index_body_uses_helper_output(self) -> None:
        from config.settings import INDEX_BODY, VECTOR_DIM

        chunk_field: Dict[str, Any] = INDEX_BODY["mappings"]["properties"]["chunk_embedding"]
        expected = build_knn_vector_field(VECTOR_DIM)
        assert chunk_field == expected
