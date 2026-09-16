"""`_bulk_with_retry` must retry only the items that actually failed.

A single bulk() call executes every item independently, so one item hitting a
transient condition (e.g. the write thread pool briefly rejecting a request)
sets `errors: true` for the whole response even though the rest of the
document's chunks were written. Since every op is an idempotent upsert,
retrying is safe - but resending the *whole* request would re-submit
already-succeeded items and, under sustained load, could fail a different
subset on each attempt, leaving the file marked failed even though every
chunk eventually succeeded. So each retry must resend only the items still
failing. A genuine content/schema error must still raise immediately, without
wasting retries.
"""

from typing import Any

import pytest

from services.document_index_writer import DocumentIndexWriter


class ScriptedBulkClient:
    """Returns each scripted response in order, one per `bulk()` call, and
    records the request bodies it was sent."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls = 0
        self.request_bodies: list[list[dict[str, Any]]] = []

    async def bulk(self, *, body: list[dict[str, Any]], refresh: bool | str) -> dict[str, Any]:
        self.request_bodies.append(body)
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


def _bulk_body() -> list[dict[str, Any]]:
    return [
        {"index": {"_id": "chunk-1"}},
        {"text": "a"},
        {"index": {"_id": "chunk-2"}},
        {"text": "b"},
    ]


@pytest.mark.asyncio
async def test_retries_only_the_failed_item(monkeypatch):
    monkeypatch.setattr("services.document_index_writer._BULK_RETRY_DELAY_SECONDS", 0)
    client = ScriptedBulkClient(
        [
            {
                "errors": True,
                "items": [
                    {"index": {"_id": "chunk-1", "status": 201}},
                    {
                        "index": {
                            "_id": "chunk-2",
                            "status": 429,
                            "error": {
                                "type": "es_rejected_execution_exception",
                                "reason": "queue full",
                            },
                        }
                    },
                ],
            },
            {"errors": False, "items": [{"index": {"_id": "chunk-2", "status": 201}}]},
        ]
    )

    writer = DocumentIndexWriter()
    result = await writer._bulk_with_retry(client, _bulk_body(), refresh=False)

    assert client.calls == 2
    assert result["errors"] is False
    # The retry must resend only chunk-2's action/document pair, not chunk-1's.
    assert client.request_bodies[1] == [{"index": {"_id": "chunk-2"}}, {"text": "b"}]
    # The merged result keeps chunk-1's original successful item.
    assert result["items"][0]["index"]["_id"] == "chunk-1"
    assert result["items"][1]["index"]["_id"] == "chunk-2"


@pytest.mark.asyncio
async def test_does_not_retry_non_retryable_error(monkeypatch):
    monkeypatch.setattr("services.document_index_writer._BULK_RETRY_DELAY_SECONDS", 0)
    client = ScriptedBulkClient(
        [
            {
                "errors": True,
                "items": [
                    {"index": {"_id": "chunk-1", "status": 201}},
                    {
                        "index": {
                            "_id": "chunk-2",
                            "status": 400,
                            "error": {"type": "mapper_parsing_exception", "reason": "bad field"},
                        }
                    },
                ],
            },
        ]
    )

    writer = DocumentIndexWriter()
    result = await writer._bulk_with_retry(client, _bulk_body(), refresh=False)

    assert client.calls == 1
    assert result["errors"] is True


@pytest.mark.asyncio
async def test_gives_up_after_max_retries_still_failing(monkeypatch):
    monkeypatch.setattr("services.document_index_writer._BULK_RETRY_DELAY_SECONDS", 0)
    initial_response = {
        "errors": True,
        "items": [
            {"index": {"_id": "chunk-1", "status": 201}},
            {
                "index": {
                    "_id": "chunk-2",
                    "status": 429,
                    "error": {"type": "es_rejected_execution_exception", "reason": "queue full"},
                }
            },
        ],
    }
    # Once chunk-1 has succeeded, only chunk-2 is resent on every later
    # attempt, so those responses carry a single item.
    persistent_chunk2_failure = {
        "errors": True,
        "items": [
            {
                "index": {
                    "_id": "chunk-2",
                    "status": 429,
                    "error": {"type": "es_rejected_execution_exception", "reason": "queue full"},
                }
            },
        ],
    }
    client = ScriptedBulkClient([initial_response, persistent_chunk2_failure])

    writer = DocumentIndexWriter()
    result = await writer._bulk_with_retry(client, _bulk_body(), refresh=False)

    # Initial attempt + _MAX_BULK_RETRIES retries, all exhausted.
    assert client.calls == 3
    assert result["errors"] is True
    # chunk-1's earlier success must survive even though the file overall failed.
    assert result["items"][0]["index"]["_id"] == "chunk-1"
    assert "error" not in result["items"][0]["index"]
    # Every retry after the first call resends only chunk-2's pair.
    assert all(
        body == [{"index": {"_id": "chunk-2"}}, {"text": "b"}] for body in client.request_bodies[1:]
    )
