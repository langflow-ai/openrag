"""Tests for extract_relevant picture-description (VLM annotation) handling.

Regression coverage for image-only documents on the non-Langflow ingestion
path: Docling stores VLM captions under pictures[].annotations, and dropping
them left such documents with zero chunks (surfaced as "corrupted or invalid").
"""

from src.utils.document_processing import extract_relevant


def _description(text: str) -> dict:
    return {"kind": "description", "text": text, "provenance": "vlm-model"}


def test_image_only_doc_yields_picture_chunk():
    """A document with no text layer still produces a chunk from its caption."""
    doc = {
        "origin": {"binary_hash": "h1", "filename": "cat.pdf", "mimetype": "application/pdf"},
        "texts": [],
        "tables": [],
        "pictures": [
            {"prov": [{"page_no": 1}], "annotations": [_description("a cat on a mat")]},
        ],
    }
    result = extract_relevant(doc)
    picture_chunks = [c for c in result["chunks"] if c["type"] == "picture"]
    assert len(picture_chunks) == 1
    assert picture_chunks[0]["text"] == "a cat on a mat"
    assert picture_chunks[0]["page"] == 1
    assert picture_chunks[0]["picture_index"] == 0


def test_multiple_descriptions_joined():
    doc = {
        "origin": {},
        "pictures": [
            {
                "prov": [{"page_no": 3}],
                "annotations": [_description("line one"), _description("line two")],
            }
        ],
    }
    chunk = extract_relevant(doc)["chunks"][0]
    assert chunk["text"] == "line one\nline two"
    assert chunk["page"] == 3


def test_classification_only_annotation_yields_placeholder():
    """Non-description annotations (e.g. classification) produce an image placeholder."""
    doc = {
        "origin": {},
        "pictures": [
            {
                "prov": [{"page_no": 1}],
                "annotations": [
                    {
                        "kind": "classification",
                        "provenance": "cls",
                        "predicted_classes": [{"class_name": "photo", "confidence": 0.9}],
                    }
                ],
            }
        ],
    }
    chunks = extract_relevant(doc)["chunks"]
    assert len(chunks) == 1
    assert chunks[0]["text"] == "<!-- image -->"
    assert chunks[0]["page"] == 1


def test_uncaptioned_pictures_do_not_add_placeholders_when_content_exists():
    doc = {
        "origin": {},
        "texts": [{"prov": [{"page_no": 1}], "text": "body text"}],
        "pictures": [
            {"prov": [{"page_no": 1}], "annotations": [_description("   ")]},
            {"prov": [{"page_no": 2}], "annotations": []},
        ],
    }
    chunks = extract_relevant(doc)["chunks"]
    assert len(chunks) == 1
    assert chunks[0]["type"] == "text"
    assert chunks[0]["text"] == "body text"


def test_uncaptioned_image_only_doc_yields_one_placeholder():
    doc = {
        "origin": {},
        "pictures": [
            {"prov": [{"page_no": 2}], "annotations": [_description("   ")]},
            {"prov": [{"page_no": 3}], "annotations": []},
        ],
    }
    chunks = extract_relevant(doc)["chunks"]
    assert len(chunks) == 1
    assert chunks[0]["type"] == "picture"
    assert chunks[0]["text"] == "<!-- image -->"
    assert chunks[0]["page"] == 2
    assert chunks[0]["picture_index"] == 0


def test_missing_prov_defaults_to_page_one():
    doc = {"origin": {}, "pictures": [{"annotations": [_description("no prov")]}]}
    chunk = extract_relevant(doc)["chunks"][0]
    assert chunk["page"] == 1
    assert chunk["text"] == "no prov"


def test_text_and_picture_chunks_coexist():
    doc = {
        "origin": {},
        "texts": [{"prov": [{"page_no": 1}], "text": "body text"}],
        "pictures": [{"prov": [{"page_no": 1}], "annotations": [_description("a diagram")]}],
    }
    result = extract_relevant(doc)
    types = {c["type"] for c in result["chunks"]}
    assert types == {"text", "picture"}
    picture_chunk = next(c for c in result["chunks"] if c["type"] == "picture")
    assert picture_chunk["text"] == "a diagram"
