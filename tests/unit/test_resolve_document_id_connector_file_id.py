"""Unit tests for `LangflowFileService._resolve_document_id`'s connector_file_id path.

Bucket-style connectors (IBM COS, Azure Blob, AWS S3) build their document
identity from the raw, potentially non-ASCII object key (e.g. "bucket::報告書.pdf").
That raw value must never be used verbatim as `document_id` — it has to travel
through ASCII-only HTTP headers (X-Langflow-Global-Var-DOCUMENT_ID) and is used
as the OpenSearch chunk `_id`. These tests pin the fix: when a `connector_file_id`
is supplied, `document_id` is a stable ASCII hash of it, never the raw value.
"""

from services.langflow_file_service import LangflowFileService


def _service():
    return LangflowFileService(docling_service=None)


def test_connector_file_id_hashed_into_ascii_document_id():
    svc = _service()
    raw_id = "my-bucket::報告書.pdf"

    resolved = svc._resolve_document_id(None, None, raw_id)

    assert resolved != raw_id
    resolved.encode("ascii")  # must not raise


def test_connector_file_id_hash_is_deterministic():
    svc = _service()
    raw_id = "my-bucket::報告書.pdf"

    first = svc._resolve_document_id(None, None, raw_id)
    second = svc._resolve_document_id(None, None, raw_id)

    assert first == second


def test_different_connector_file_ids_hash_differently():
    svc = _service()

    a = svc._resolve_document_id(None, None, "bucket::a.pdf")
    b = svc._resolve_document_id(None, None, "bucket::b.pdf")

    assert a != b


def test_connector_file_id_takes_precedence_over_explicit_document_id():
    svc = _service()

    resolved = svc._resolve_document_id(None, "explicit-id", "bucket::報告書.pdf")

    assert resolved != "explicit-id"


def test_ascii_connector_file_id_still_gets_hashed_for_consistency():
    """Even an already-ASCII connector_file_id (e.g. Google Drive's opaque file
    id) is hashed, so document_id stays a stable, bounded-length identifier
    regardless of connector type — not just a non-ASCII special case."""
    svc = _service()

    resolved = svc._resolve_document_id(None, None, "1a2B3cD4E5f")

    assert resolved != "1a2B3cD4E5f"


def test_no_connector_file_id_falls_back_to_explicit_document_id():
    svc = _service()

    resolved = svc._resolve_document_id(None, "explicit-id", None)

    assert resolved == "explicit-id"


def test_no_ids_falls_back_to_content_hash():
    svc = _service()
    file_tuples = [("報告書.pdf", b"file content", "application/pdf")]

    resolved = svc._resolve_document_id(file_tuples, None, None)

    assert resolved
    resolved.encode("ascii")  # must not raise
