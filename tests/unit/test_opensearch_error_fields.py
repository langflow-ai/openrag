"""Shared extraction of OpenSearch error context (status/error/info/reason).

`opensearch_error_fields` / `opensearch_error_reason` give every
OpenSearch-touching call site one schema for surfacing the real cause of an
otherwise-opaque `TransportError`, instead of each site re-deriving it with
inconsistent field names.
"""

from utils.opensearch_utils import opensearch_error_fields, opensearch_error_reason


class _TransportErrorLike(Exception):
    def __init__(self, status_code, error, info, message):
        super().__init__(message)
        self.status_code = status_code
        self.error = error
        self.info = info
        self._message = message

    def __str__(self):
        return self._message


def _mapping_error():
    info = {
        "error": {
            "type": "mapper_parsing_exception",
            "reason": "top-level reason",
            "root_cause": [
                {
                    "type": "mapper_parsing_exception",
                    "reason": "failed to parse field [created_time] of type [date]",
                }
            ],
        }
    }
    return _TransportErrorLike(400, "mapper_parsing_exception", info, "TransportError(400, ...)")


def test_fields_surface_status_error_info_and_root_cause():
    fields = opensearch_error_fields(_mapping_error())

    assert fields["opensearch_status"] == 400
    assert fields["opensearch_error"] == "mapper_parsing_exception"
    assert fields["opensearch_root_cause"]["reason"].endswith("[date]")
    assert "error" in fields["opensearch_info"]


def test_reason_prefers_root_cause_over_top_level():
    assert opensearch_error_reason(_mapping_error()) == (
        "failed to parse field [created_time] of type [date]"
    )


def test_reason_falls_back_to_top_level_when_no_root_cause():
    err = _TransportErrorLike(400, "x", {"error": {"reason": "only top level"}}, "msg")
    assert opensearch_error_reason(err) == "only top level"


def test_plain_exception_yields_no_fields_and_no_reason():
    err = ValueError("not an opensearch error")
    assert opensearch_error_fields(err) == {}
    assert opensearch_error_reason(err) is None
