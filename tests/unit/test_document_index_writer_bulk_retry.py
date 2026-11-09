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


@pytest.mark.asyncio
async def test_short_items_list_raises(monkeypatch):
    """A response with fewer items than pending requests must raise immediately
    rather than returning None-filled slots that callers cannot safely iterate."""
    monkeypatch.setattr("services.document_index_writer._BULK_RETRY_DELAY_SECONDS", 0)
    # Two pairs were sent, but the server only returns one item.
    client = ScriptedBulkClient(
        [{"errors": False, "items": [{"index": {"_id": "chunk-1", "status": 201}}]}]
    )

    writer = DocumentIndexWriter()
    with pytest.raises(RuntimeError, match="malformed response"):
        await writer._bulk_with_retry(client, _bulk_body(), refresh=False)

    assert client.calls == 1


@pytest.mark.asyncio
async def test_top_level_errors_true_without_per_item_errors_is_preserved():
    """If the server returns errors: true but no item carries an error dict,
    the top-level flag must be preserved rather than overwritten with False."""
    client = ScriptedBulkClient(
        [
            {
                "errors": True,
                "items": [
                    {"index": {"_id": "chunk-1", "status": 201}},
                    {"index": {"_id": "chunk-2", "status": 201}},
                ],
            }
        ]
    )

    writer = DocumentIndexWriter()
    result = await writer._bulk_with_retry(client, _bulk_body(), refresh=False)

    assert client.calls == 1
    assert result["errors"] is True


def test_odd_length_bulk_body_raises():
    """An odd-length bulk_body means a mismatched action/document pair — must
    raise immediately rather than silently misaligning the request."""
    writer = DocumentIndexWriter()
    with pytest.raises(ValueError, match="action/document pairs"):
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            writer._bulk_with_retry(None, [{"index": {"_id": "chunk-1"}}], refresh=False)
        )


@pytest.mark.asyncio
async def test_version_conflict_is_not_retried(monkeypatch):
    """version_conflict_engine_exception must not be retried — conflicts are
    caused by concurrent writes and are not transient cluster conditions."""
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
                            "status": 409,
                            "error": {
                                "type": "version_conflict_engine_exception",
                                "reason": "document already exists",
                            },
                        }
                    },
                ],
            }
        ]
    )

    writer = DocumentIndexWriter()
    result = await writer._bulk_with_retry(client, _bulk_body(), refresh=False)

    assert client.calls == 1
    assert result["errors"] is True


@pytest.mark.asyncio
async def test_item_error_fallback_for_unknown_action_type():
    """_item_error must still extract the error dict when the item does not
    use a recognised action key (index/create/update), falling back to the
    item itself."""
    writer = DocumentIndexWriter()
    item_with_unknown_action = {
        "delete": {
            "_id": "chunk-1",
            "status": 404,
            "error": {"type": "not_found", "reason": "document missing"},
        }
    }
    # The fallback `or item` path: none of index/create/update match, so
    # _item_error receives the raw item dict and looks for "error" on it
    # directly — which is absent at the top level, so returns None.
    assert writer._item_error(item_with_unknown_action) is None

    # Confirm an item that truly has no recognised action and carries a
    # top-level error key is picked up by the fallback.
    bare_error_item: dict[str, Any] = {"error": {"type": "some_exception", "reason": "boom"}}
    assert writer._item_error(bare_error_item) == {"type": "some_exception", "reason": "boom"}
