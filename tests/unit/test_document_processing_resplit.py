"""Tests for resplit_chunks_character_windows."""

from src.utils.document_processing import resplit_chunks_character_windows


def test_invalid_returns_original():
    chunks = [{"page": 1, "text": "hello world" * 50}]
    assert resplit_chunks_character_windows(chunks, 0, 0) is chunks
    assert resplit_chunks_character_windows(chunks, 10, 10) is chunks
    assert resplit_chunks_character_windows(chunks, 5, 6) is chunks


def test_non_dict_chunk_passthrough():
    chunks = ["not-a-dict", {"page": 1, "text": "x" * 30}]
    out = resplit_chunks_character_windows(chunks, 10, 2)
    assert out[0] == "not-a-dict"
    assert len(out) == 1 + 4  # one long dict chunk -> 4 windows


def test_short_text_unchanged_count():
    chunks = [{"page": 2, "type": "text", "text": "short"}]
    out = resplit_chunks_character_windows(chunks, 100, 20)
    assert len(out) == 1
    assert out[0]["text"] == "short"
    assert out[0]["page"] == 2


def test_long_text_windows_with_overlap():
    # 22 chars, size 10, overlap 4 -> stride 6; third window reaches end
    text = "abcdefghijklmnopqrstuv"
    assert len(text) == 22
    chunks = [{"page": 1, "text": text}]
    out = resplit_chunks_character_windows(chunks, 10, 4)
    assert len(out) == 3
    assert out[0]["text"] == "abcdefghij"
    assert out[1]["text"] == "ghijklmnop"
    assert out[2]["text"] == "mnopqrstuv"


def test_extract_relevant_with_missing_page_no():
    from src.utils.document_processing import extract_relevant

    # Docling JSON representation where page_no is missing in prov (e.g. for asciidoc/html)
    doc_dict = {
        "origin": {"binary_hash": "hash123", "filename": "test.adoc", "mimetype": "text/asciidoc"},
        "texts": [
            {
                "text": "Hello Asciidoc World!",
                "prov": [],  # empty prov
            },
            {
                "text": "Second paragraph of text.",
                "prov": [{"some_other_key": "val"}],  # prov present but no page_no
            },
        ],
        "tables": [],
    }

    result = extract_relevant(doc_dict)
    assert result["id"] == "hash123"
    assert result["filename"] == "test.adoc"
    assert result["mimetype"] == "text/asciidoc"
    assert len(result["chunks"]) == 1
    assert result["chunks"][0]["page"] == 1
    assert "Hello Asciidoc World!" in result["chunks"][0]["text"]
    assert "Second paragraph of text." in result["chunks"][0]["text"]
