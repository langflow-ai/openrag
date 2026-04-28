"""Unit tests for LangflowFileService.merge_ui_ingest_settings_into_tweaks."""

from src.services.langflow_file_service import LangflowFileService


def test_merge_no_settings_returns_tweaks_copy():
    base = {"OtherNode": {"x": 1}}
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(base, None)
    assert out == base
    assert out is not base


def test_merge_empty_settings_returns_tweaks_only():
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(None, {})
    assert out == {}


def test_merge_chunk_fields_populate_split_text():
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(
        None,
        {"chunkSize": 512, "chunkOverlap": 64, "separator": "\n\n"},
    )
    assert out["SplitText-QIKhg"] == {
        "chunk_size": 512,
        "chunk_overlap": 64,
        "separator": "\n\n",
    }


def test_merge_chunk_partial_only_sets_provided_keys():
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(
        None,
        {"chunkSize": 1000},
    )
    assert out["SplitText-QIKhg"] == {"chunk_size": 1000}


def test_merge_preserves_and_extends_existing_split_text():
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(
        {"SplitText-QIKhg": {"chunk_size": 100, "existing": "keep"}},
        {"chunkOverlap": 20},
    )
    assert out["SplitText-QIKhg"] == {
        "chunk_size": 100,
        "existing": "keep",
        "chunk_overlap": 20,
    }


def test_merge_embedding_model_sets_openai_embeddings_tweak():
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(
        None,
        {"embeddingModel": "text-embedding-3-large"},
    )
    assert out["OpenAIEmbeddings-joRJ6"] == {"model": "text-embedding-3-large"}


def test_merge_embedding_extends_existing_openai_tweak():
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks(
        {"OpenAIEmbeddings-joRJ6": {"api_key": "masked"}},
        {"embeddingModel": "text-embedding-3-small"},
    )
    assert out["OpenAIEmbeddings-joRJ6"] == {
        "api_key": "masked",
        "model": "text-embedding-3-small",
    }


def test_connector_style_settings_without_embedding_only_split_text():
    """Simulate langflow_connector_service: pop embeddingModel, then merge."""
    settings = {
        "chunkSize": 800,
        "chunkOverlap": 100,
        "ocr": True,
        "embeddingModel": "should-be-stripped",
    }
    connector = dict(settings)
    connector.pop("embeddingModel", None)
    out = LangflowFileService.merge_ui_ingest_settings_into_tweaks({}, connector)
    assert "OpenAIEmbeddings-joRJ6" not in out
    assert out["SplitText-QIKhg"]["chunk_size"] == 800
