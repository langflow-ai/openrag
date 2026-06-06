"""`_raise_for_bulk_errors` must surface the real per-item failures.

A bulk response interleaves successes and failures; the check must report only
the items that actually failed, and must never degrade to an empty `[]` message
when the `errors` flag is set.
"""

import pytest

from services.document_index_writer import DocumentIndexWriter


def test_no_error_when_errors_flag_absent():
    # Should not raise.
    DocumentIndexWriter._raise_for_bulk_errors({"errors": False, "items": []})
    DocumentIndexWriter._raise_for_bulk_errors({"took": 1})


def test_reports_only_failed_items_from_interleaved_response():
    result = {
        "errors": True,
        "items": [
            {"index": {"_id": "ok-1", "status": 201}},
            {
                "index": {
                    "_id": "bad-1",
                    "status": 400,
                    "error": {"type": "mapper_parsing_exception", "reason": "field [created_time]"},
                }
            },
            {"index": {"_id": "ok-2", "status": 200}},
        ],
    }
    with pytest.raises(RuntimeError) as excinfo:
        DocumentIndexWriter._raise_for_bulk_errors(result)

    message = str(excinfo.value)
    assert "bad-1" in message
    assert "created_time" in message
    # Successful items are not reported as failures.
    assert "ok-1" not in message
    assert "ok-2" not in message


def test_empty_failures_falls_back_to_raw_items_not_empty_list():
    # `errors` set but no item carries an error body (contradictory/rare).
    result = {
        "errors": True,
        "items": [{"index": {"_id": "x", "status": 201}}],
    }
    with pytest.raises(RuntimeError) as excinfo:
        DocumentIndexWriter._raise_for_bulk_errors(result)

    message = str(excinfo.value)
    # Must keep some detail rather than degrade to "... failed: []".
    assert message != "OpenSearch bulk indexing failed: []"
    assert "x" in message
