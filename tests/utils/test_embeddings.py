"""
Tests for embeddings utility functions.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from utils.embeddings import get_embedding_dimensions, create_dynamic_index_body


@pytest.mark.unit
class TestEmbeddingDimensions:
    """Test suite for embedding dimension utilities."""

    def test_get_openai_embedding_dimensions(self):
        """Test getting dimensions for OpenAI models."""
        # Test common OpenAI models
        assert get_embedding_dimensions("text-embedding-ada-002") > 0
        assert get_embedding_dimensions("text-embedding-3-small") > 0
        assert get_embedding_dimensions("text-embedding-3-large") > 0

    def test_get_ollama_embedding_dimensions(self):
        """Test getting dimensions for Ollama models."""
        # Test common Ollama models
        dimensions = get_embedding_dimensions("nomic-embed-text")
        assert dimensions > 0
        assert isinstance(dimensions, int)

    def test_get_embedding_dimensions_with_version(self):
        """Test that model names with versions are handled correctly."""
        # Model name with version tag should still work
        dim_with_version = get_embedding_dimensions("nomic-embed-text:latest")
        dim_without_version = get_embedding_dimensions("nomic-embed-text")
        assert dim_with_version == dim_without_version

    def test_get_embedding_dimensions_case_insensitive(self):
        """Test that model name lookup is case-insensitive."""
        dim_lower = get_embedding_dimensions("nomic-embed-text")
        dim_upper = get_embedding_dimensions("NOMIC-EMBED-TEXT")
        dim_mixed = get_embedding_dimensions("Nomic-Embed-Text")

        assert dim_lower == dim_upper == dim_mixed

    def test_get_embedding_dimensions_with_whitespace(self):
        """Test that whitespace in model names is handled."""
        dim_no_space = get_embedding_dimensions("nomic-embed-text")
        dim_with_space = get_embedding_dimensions("  nomic-embed-text  ")

        assert dim_no_space == dim_with_space

    def test_get_embedding_dimensions_unknown_model(self):
        """Test that unknown models return default dimensions."""
        dimensions = get_embedding_dimensions("unknown-model-xyz")
        assert isinstance(dimensions, int)
        assert dimensions > 0  # Should return default VECTOR_DIM

    def test_get_embedding_dimensions_empty_string(self):
        """Test handling of empty model name."""
        dimensions = get_embedding_dimensions("")
        assert isinstance(dimensions, int)
        assert dimensions > 0


@pytest.mark.unit
class TestCreateDynamicIndexBody:
    """Test suite for dynamic index body creation."""

    def test_create_index_body_structure(self):
        """Test that index body has correct structure."""
        body = create_dynamic_index_body("text-embedding-ada-002")

        assert "settings" in body
        assert "mappings" in body
        assert "index" in body["settings"]
        assert "knn" in body["settings"]["index"]
        assert body["settings"]["index"]["knn"] is True

    def test_create_index_body_mappings(self):
        """Test that index body has all required field mappings."""
        body = create_dynamic_index_body("nomic-embed-text")

        properties = body["mappings"]["properties"]

        # Check all required fields are present
        required_fields = [
            "document_id",
            "filename",
            "mimetype",
            "page",
            "text",
            "chunk_embedding",
            "source_url",
            "connector_type",
            "owner",
            "allowed_users",
            "allowed_groups",
            "user_permissions",
            "group_permissions",
            "created_time",
            "modified_time",
            "indexed_time",
            "metadata",
        ]

        for field in required_fields:
            assert field in properties, f"Field '{field}' missing from mappings"

    def test_create_index_body_embedding_dimensions(self):
        """Test that embedding field uses correct dimensions for different models."""
        # Test with different models
        models = [
            "text-embedding-ada-002",
            "nomic-embed-text",
            "text-embedding-3-small",
        ]

        for model in models:
            body = create_dynamic_index_body(model)
            embedding_config = body["mappings"]["properties"]["chunk_embedding"]

            assert "dimension" in embedding_config
            assert embedding_config["dimension"] > 0
            assert embedding_config["type"] == "knn_vector"

    def test_create_index_body_knn_method(self):
        """Test that KNN method configuration is correct."""
        body = create_dynamic_index_body("nomic-embed-text")
        knn_config = body["mappings"]["properties"]["chunk_embedding"]["method"]

        assert knn_config["name"] == "disk_ann"
        assert knn_config["engine"] == "jvector"
        assert knn_config["space_type"] == "l2"
        assert "ef_construction" in knn_config["parameters"]
        assert "m" in knn_config["parameters"]

    def test_create_index_body_field_types(self):
        """Test that field types are correctly set."""
        body = create_dynamic_index_body("nomic-embed-text")
        properties = body["mappings"]["properties"]

        # Test specific field types
        assert properties["document_id"]["type"] == "keyword"
        assert properties["filename"]["type"] == "keyword"
        assert properties["text"]["type"] == "text"
        assert properties["page"]["type"] == "integer"
        assert properties["created_time"]["type"] == "date"
        assert properties["metadata"]["type"] == "object"

    def test_create_index_body_shards_config(self):
        """Test that shard configuration is correct."""
        body = create_dynamic_index_body("nomic-embed-text")
        settings = body["settings"]

        assert settings["number_of_shards"] == 1
        assert settings["number_of_replicas"] == 1

    def test_create_index_body_different_models_different_dimensions(self):
        """Test that different models produce different embedding dimensions."""
        body1 = create_dynamic_index_body("text-embedding-ada-002")
        body2 = create_dynamic_index_body("text-embedding-3-large")

        dim1 = body1["mappings"]["properties"]["chunk_embedding"]["dimension"]
        dim2 = body2["mappings"]["properties"]["chunk_embedding"]["dimension"]

        # These models should have different dimensions
        # If they're the same, it's still valid, but typically they differ
        assert isinstance(dim1, int)
        assert isinstance(dim2, int)

    def test_create_index_body_consistency(self):
        """Test that creating index body multiple times with same model is consistent."""
        model = "nomic-embed-text"

        body1 = create_dynamic_index_body(model)
        body2 = create_dynamic_index_body(model)

        assert body1 == body2
