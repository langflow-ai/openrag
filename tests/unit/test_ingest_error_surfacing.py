"""Connector/Langflow ingest failures must surface the real OpenSearch cause.

A bare `str(e)` on an OpenSearch transport error frequently hides the actual
exception `type`, `reason`, and the offending field, leaving an opaque 500.
`_describe_ingest_error` digs those out of the error `info` body so both the log
line and the 500 detail name the cause (e.g. a `mapper_parsing_exception` on
`created_time` that only connector documents trigger).
"""

from api.langflow_ingest import _describe_ingest_error


class _TransportErrorLike(Exception):
    """Mimics opensearchpy.TransportError's status_code/info attributes."""

    def __init__(self, status_code, info, message):
        super().__init__(message)
        self.status_code = status_code
        self.info = info
        self._message = message

    def __str__(self):
        return self._message


def test_describe_ingest_error_extracts_opensearch_reason_and_field():
    info = {
        "error": {
            "type": "mapper_parsing_exception",
            "reason": "failed to parse field [created_time] of type [date]",
            "root_cause": [
                {
                    "type": "mapper_parsing_exception",
                    "reason": "failed to parse field [created_time] of type [date]",
                }
            ],
        }
    }
    err = _TransportErrorLike(400, info, "TransportError(400, 'mapper_parsing_exception')")

    log_fields, detail = _describe_ingest_error(err)

    assert log_fields["error_type"] == "_TransportErrorLike"
    assert log_fields["opensearch_status"] == 400
    assert log_fields["opensearch_info"] == info
    assert log_fields["opensearch_root_cause"]["type"] == "mapper_parsing_exception"
    # The 500 detail now names the offending field instead of just the class.
    assert "created_time" in detail
    assert "opensearch:" in detail


def test_describe_ingest_error_plain_exception_is_still_described():
    log_fields, detail = _describe_ingest_error(
        ValueError("Cannot index chunks with empty embeddings")
    )

    assert log_fields["error_type"] == "ValueError"
    assert log_fields["error"] == "Cannot index chunks with empty embeddings"
    # No OpenSearch body to mine -> no synthetic status/info, detail unchanged.
    assert "opensearch_status" not in log_fields
    assert "opensearch_info" not in log_fields
    assert detail == "Cannot index chunks with empty embeddings"
