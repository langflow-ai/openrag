"""Unit tests for provider error message formatting."""

from __future__ import annotations

import json

from api.provider_validation import (
    _parse_json_error_message,
    format_provider_error_message,
)


def test_parse_ibm_iam_error_message():
    payload = {
        "errorCode": "BXNIM0415E",
        "errorMessage": "Provided API key could not be found.",
        "context": {
            "requestId": "cGI3bGc-8b0786d649104dca99ef114c2a834f66",
            "url": "https://iam.cloud.ibm.com",
        },
    }
    assert _parse_json_error_message(json.dumps(payload)) == "Provided API key could not be found."


def test_format_ibm_auth_failure_strips_context_json():
    raw = (
        'Failed to authenticate with IBM Watson: {"errorCode":"BXNIM0415E",'
        '"errorMessage":"Provided API key could not be found.",'
        '"context":{"requestId":"abc","url":"https://iam.cloud.ibm.com"}}'
    )
    assert format_provider_error_message(raw) == (
        "Failed to authenticate with IBM Watson: Provided API key could not be found."
    )


def test_format_dedupes_identical_auth_failures_with_different_request_ids():
    first = (
        'Failed to authenticate with IBM Watson: {"errorCode":"BXNIM0415E",'
        '"errorMessage":"Provided API key could not be found.",'
        '"context":{"requestId":"req-1"}}'
    )
    second = (
        'Failed to authenticate with IBM Watson: {"errorCode":"BXNIM0415E",'
        '"errorMessage":"Provided API key could not be found.",'
        '"context":{"requestId":"req-2"}}'
    )
    assert format_provider_error_message(first) == format_provider_error_message(second)
