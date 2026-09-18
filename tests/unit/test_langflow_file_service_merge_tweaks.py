"""Unit tests for LangflowFileService.merge_ui_ingest_settings_into_tweaks."""

from types import SimpleNamespace

from src.services.langflow_file_service import BEDROCK_MAX_CHUNK_CHARS, LangflowFileService


def _fake_config(*, embedding_provider="openai", embedding_model="text-embedding-3-small"):
    return SimpleNamespace(
        knowledge=SimpleNamespace(
            table_structure=False,
            ocr=False,
            picture_descriptions=False,
            chunk_size=1000,
            chunk_overlap=200,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
        )
    )


def test_merge_no_settings_returns_tweaks_copy():
    base = {"OtherNode": {"x": 1}}
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(base, None)
    assert out["OtherNode"] == {"x": 1}
    assert "Docling Serve" in out
    assert "Split Text" in out


def test_merge_empty_settings_returns_tweaks_only():
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(None, {})
    assert "Docling Serve" in out
    assert "Split Text" in out


def test_merge_chunk_fields_populate_split_text():
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(
        None,
        {"chunkSize": 512, "chunkOverlap": 64, "separator": "\n\n"},
    )
    assert out["Split Text"] == {
        "chunk_size": 512,
        "chunk_overlap": 64,
        "separator": "\n\n",
    }


def test_merge_chunk_partial_only_sets_provided_keys():
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(
        None,
        {"chunkSize": 1000},
    )
    assert out["Split Text"]["chunk_size"] == 1000
    assert out["Split Text"]["chunk_overlap"] == 200


def test_merge_preserves_and_extends_existing_split_text():
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(
        {"Split Text": {"chunk_size": 100, "existing": "keep"}},
        {"chunkOverlap": 20},
    )
    assert out["Split Text"] == {
        "chunk_size": 100,
        "existing": "keep",
        "chunk_overlap": 20,
    }


def test_merge_embedding_model_is_ignored_in_tweaks():
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(
        None,
        {"embeddingModel": "text-embedding-3-large"},
    )
    assert "OpenAIEmbeddings-joRJ6" not in out
    assert "Docling Serve" in out
    assert "Split Text" in out


def test_connector_style_settings_without_embedding_only_split_text():
    """Embedding model is not mapped to tweaks; split settings still apply."""
    settings = {
        "chunkSize": 800,
        "chunkOverlap": 100,
        "ocr": True,
        "embeddingModel": "ignored",
    }
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks({}, settings)
    assert "OpenAIEmbeddings-joRJ6" not in out
    assert out["Split Text"]["chunk_size"] == 800
    assert out["Split Text"]["chunk_overlap"] == 100


# ---------------------------------------------------------------------------
# Bedrock/Cohere 512-token chunk cap (regression: langflow ingest had no
# Bedrock-aware cap at all, unlike models/processors.py's non-Langflow path,
# and Bedrock's Cohere Embed models hard-reject inputs over 512 tokens).
# ---------------------------------------------------------------------------


def test_bedrock_embedding_provider_clamps_large_ui_chunk_size(monkeypatch):
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: _fake_config(embedding_provider="bedrock"),
    )
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(
        None,
        {"chunkSize": 4000},
    )
    assert out["Split Text"]["chunk_size"] == BEDROCK_MAX_CHUNK_CHARS


def test_bedrock_embedding_provider_clamps_config_default_chunk_size(monkeypatch):
    """No UI override at all - the config-default chunk_size must still be
    clamped, since Split Text otherwise applies it unchanged."""
    config = _fake_config(embedding_provider="bedrock")
    config.knowledge.chunk_size = 4000
    monkeypatch.setattr("config.settings.get_openrag_config", lambda: config)

    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(None, None)
    assert out["Split Text"]["chunk_size"] == BEDROCK_MAX_CHUNK_CHARS


def test_bedrock_embedding_provider_leaves_small_chunk_size_unclamped(monkeypatch):
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: _fake_config(embedding_provider="bedrock"),
    )
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(
        None,
        {"chunkSize": 500},
    )
    assert out["Split Text"]["chunk_size"] == 500


def test_cohere_embedding_model_clamps_even_for_a_non_bedrock_provider_field(monkeypatch):
    """The 512-token limit is Cohere Embed's, not Bedrock-the-provider's -
    matches is_cohere_embedding_model()'s model-name-based detection."""
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: _fake_config(embedding_provider="openai", embedding_model="cohere.embed-v3"),
    )
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(
        None,
        {"chunkSize": 4000},
    )
    assert out["Split Text"]["chunk_size"] == BEDROCK_MAX_CHUNK_CHARS


def test_non_bedrock_provider_chunk_size_passes_through_unclamped(monkeypatch):
    """Regression guard: openai/watsonx/ollama must be unaffected by this fix."""
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: _fake_config(embedding_provider="openai", embedding_model="text-embedding-3-large"),
    )
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(
        None,
        {"chunkSize": 4000},
    )
    assert out["Split Text"]["chunk_size"] == 4000


def test_per_request_embedding_model_override_triggers_the_clamp(monkeypatch):
    """API/connector callers can override the model per-request via
    settings["embeddingModel"] (see selected_embedding_model in
    run_ingestion_flow) - the account-wide config default is openai here,
    but the actual run uses a Cohere model, so the clamp must key off the
    effective model, not just the config default."""
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: _fake_config(embedding_provider="openai", embedding_model="text-embedding-3-large"),
    )
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(
        None,
        {"chunkSize": 4000, "embeddingModel": "cohere.embed-multilingual-v3"},
    )
    assert out["Split Text"]["chunk_size"] == BEDROCK_MAX_CHUNK_CHARS
