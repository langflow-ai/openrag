"""`_bulk_with_retry` must retry transient bulk failures but not real ones.

A single bulk() call executes every item independently, so one item hitting a
transient condition (e.g. the write thread pool briefly rejecting a request)
sets `errors: true` for the whole response even though the rest of the
document's chunks were written. Since every op is an idempotent upsert,
retrying the same request is safe and should recover from that case without
marking the whole document as failed. A genuine content/schema error must
still raise immediately, without wasting retries.
"""

from typing import Any

import pytest

from services.document_index_writer import DocumentIndexWriter


class ScriptedBulkClient:
    """Returns each scripted response in order, one per `bulk()` call."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls = 0

    async def bulk(self, *, body: list[dict[str, Any]], refresh: bool | str) -> dict[str, Any]:
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
async def test_retries_transient_error_and_recovers(monkeypatch):
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
                            "error": {"type": "es_rejected_execution_exception", "reason": "queue full"},
                        }
                    },
                ],
            },
            {"errors": False, "items": [{"index": {"_id": "chunk-1", "status": 201}}]},
        ]
    )

    writer = DocumentIndexWriter()
    result = await writer._bulk_with_retry(client, _bulk_body(), refresh=False)

    assert client.calls == 2
    assert result["errors"] is False


@pytest.mark.asyncio
async def test_does_not_retry_non_retryable_error(monkeypatch):
    monkeypatch.setattr("services.document_index_writer._BULK_RETRY_DELAY_SECONDS", 0)
    client = ScriptedBulkClient(
        [
            {
                "errors": True,
                "items": [
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
    persistent_failure = {
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
    client = ScriptedBulkClient([persistent_failure])

    writer = DocumentIndexWriter()
    result = await writer._bulk_with_retry(client, _bulk_body(), refresh=False)

    # Initial attempt + _MAX_BULK_RETRIES retries, all exhausted.
    assert client.calls == 3
    assert result["errors"] is True
