"""Unit tests for bucket-connector change detection in `src/api/connectors.py`.

Covers:
- the pure timestamp/classification helpers (`_parse_iso_to_epoch_ms`,
  `remote_is_newer_than_synced`, `classify_remote_file_change`),
- the `get_synced_file_state_map` aggregation helper,
- the whole-container (`bucket_filter`) reconciliation in `connector_sync`: only
  new + changed blobs are ingested (new as a plain batch, changed with
  replace_duplicates=True), unchanged blobs are skipped.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _rbac_allowing(*perms: str):
    """RBAC stub granting exactly `perms`.

    Unit tests run with OPENRAG_RBAC_ENFORCE=true (tests/unit/conftest.py), so
    permission checks are live and every sync now resolves
    knowledge:delete:anonymous to decide whether ownerless chunks may be
    deleted — see delete_orphan_documents.
    """
    rbac = MagicMock()
    granted = set(perms)

    async def has_permission(user_id, perm, role_override=None):
        return perm in granted

    rbac.has_permission = AsyncMock(side_effect=has_permission)
    return rbac


ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _json(response):
    return json.loads(response.body.decode())


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_parse_iso_to_epoch_ms_handles_z_and_offset_and_naive():
    from api.connectors import _parse_iso_to_epoch_ms

    z = _parse_iso_to_epoch_ms("2024-01-01T00:00:00Z")
    offset = _parse_iso_to_epoch_ms("2024-01-01T00:00:00+00:00")
    naive = _parse_iso_to_epoch_ms("2024-01-01T00:00:00")
    assert z == offset == naive == 1704067200000.0


def test_parse_iso_to_epoch_ms_returns_none_for_bad_input():
    from api.connectors import _parse_iso_to_epoch_ms

    assert _parse_iso_to_epoch_ms(None) is None
    assert _parse_iso_to_epoch_ms("") is None
    assert _parse_iso_to_epoch_ms("not-a-date") is None


def _stored(modified_ms=None, etag=None):
    from api.connectors import SyncedFileState

    return SyncedFileState(modified_time_ms=modified_ms, content_etag=etag)


def test_remote_is_newer_than_synced_true_when_strictly_newer():
    from api.connectors import remote_is_newer_than_synced

    stored = {"c::a": _stored(1704067200000.0)}  # 2024-01-01
    assert remote_is_newer_than_synced("c::a", "2024-06-01T00:00:00Z", stored) is True


def test_remote_is_newer_than_synced_false_when_same_or_older():
    from api.connectors import remote_is_newer_than_synced

    stored = {"c::a": _stored(1704067200000.0)}
    assert remote_is_newer_than_synced("c::a", "2024-01-01T00:00:00Z", stored) is False
    assert remote_is_newer_than_synced("c::a", "2023-01-01T00:00:00Z", stored) is False


def test_remote_is_newer_than_synced_tolerance_absorbs_subsecond_jitter():
    from api.connectors import remote_is_newer_than_synced

    stored = {"c::a": _stored(1704067200000.0)}
    # 500ms newer is within tolerance → not "changed".
    assert remote_is_newer_than_synced("c::a", "2024-01-01T00:00:00.500Z", stored) is False
    # 2s newer exceeds tolerance → changed.
    assert remote_is_newer_than_synced("c::a", "2024-01-01T00:00:02Z", stored) is True


def test_remote_is_newer_than_synced_false_when_no_stored_token():
    from api.connectors import remote_is_newer_than_synced

    # Missing id, or ingested-but-no-token (None) → backfill-safe False.
    assert remote_is_newer_than_synced("c::missing", "2024-06-01T00:00:00Z", {}) is False
    assert remote_is_newer_than_synced("c::a", "2024-06-01T00:00:00Z", {"c::a": _stored()}) is False


def test_classify_remote_file_change():
    from api.connectors import classify_remote_file_change

    stored = {"c::a": _stored(1704067200000.0)}
    # Not ingested → new (regardless of timestamps).
    assert classify_remote_file_change("c::new", "2024-06-01T00:00:00Z", False, stored) == "new"
    # Ingested + newer → changed.
    assert classify_remote_file_change("c::a", "2024-06-01T00:00:00Z", True, stored) == "changed"
    # Ingested + same → unchanged.
    assert classify_remote_file_change("c::a", "2024-01-01T00:00:00Z", True, stored) == "unchanged"
    # Ingested but no stored token (backfill) → unchanged.
    assert classify_remote_file_change("c::b", "2024-06-01T00:00:00Z", True, {}) == "unchanged"


# ---------------------------------------------------------------------------
# Entity-tag change detection
# ---------------------------------------------------------------------------


def test_classify_uses_etag_when_both_sides_have_one():
    """A differing etag is "changed" even when the timestamps say otherwise."""
    from api.connectors import classify_remote_file_change

    stored = {"c::a": _stored(1704067200000.0, "abc123")}
    # Same (stale) timestamp, different bytes → changed.
    assert (
        classify_remote_file_change("c::a", "2024-01-01T00:00:00Z", True, stored, "def456")
        == "changed"
    )
    # No timestamp stored at all, but the tags disagree → still changed. This is
    # the case the timestamp-only check could never see.
    assert (
        classify_remote_file_change("c::a", None, True, {"c::a": _stored(None, "abc123")}, "def456")
        == "changed"
    )


def test_classify_equal_etags_beat_a_newer_timestamp():
    """Identical bytes are unchanged even if the object's timestamp moved.

    A copy or a re-upload of the same file bumps LastModified without changing
    the content; re-ingesting it is pure waste.
    """
    from api.connectors import classify_remote_file_change

    stored = {"c::a": _stored(1704067200000.0, "abc123")}
    assert (
        classify_remote_file_change("c::a", "2024-06-01T00:00:00Z", True, stored, "abc123")
        == "unchanged"
    )


def test_classify_etag_comparison_ignores_quoting_and_weak_prefix():
    """S3 quotes its tags and HTTP may mark them weak; neither is a content change."""
    from api.connectors import classify_remote_file_change

    stored = {"c::a": _stored(1704067200000.0, "abc123")}
    assert (
        classify_remote_file_change("c::a", "2024-06-01T00:00:00Z", True, stored, '"abc123"')
        == "unchanged"
    )
    assert (
        classify_remote_file_change("c::a", "2024-06-01T00:00:00Z", True, stored, 'W/"abc123"')
        == "unchanged"
    )


def test_classify_falls_back_to_timestamp_when_an_etag_is_missing():
    """One-sided tags prove nothing, so the timestamp still decides."""
    from api.connectors import classify_remote_file_change

    stored_without_etag = {"c::a": _stored(1704067200000.0)}
    assert (
        classify_remote_file_change("c::a", "2024-06-01T00:00:00Z", True, stored_without_etag, "x")
        == "changed"
    )
    stored_with_etag = {"c::a": _stored(1704067200000.0, "abc123")}
    assert (
        classify_remote_file_change("c::a", "2024-06-01T00:00:00Z", True, stored_with_etag, None)
        == "changed"
    )


def test_has_comparable_change_signal():
    """Whether a modification could be noticed at all — what the warning counts."""
    from api.connectors import has_comparable_change_signal

    # Nothing ingested for this id.
    assert has_comparable_change_signal("c::missing", "2024-06-01T00:00:00Z", {}) is False
    # Ingested with neither signal → undetectable.
    assert (
        has_comparable_change_signal("c::a", "2024-06-01T00:00:00Z", {"c::a": _stored()}) is False
    )
    # Stored etag but the listing reports none → falls back to timestamps, and
    # there is no stored timestamp either.
    assert (
        has_comparable_change_signal("c::a", "2024-06-01T00:00:00Z", {"c::a": _stored(None, "e1")})
        is False
    )
    # Either signal comparable on both sides → detectable.
    assert (
        has_comparable_change_signal(
            "c::a", "2024-06-01T00:00:00Z", {"c::a": _stored(None, "e1")}, "e2"
        )
        is True
    )
    assert (
        has_comparable_change_signal(
            "c::a", "2024-06-01T00:00:00Z", {"c::a": _stored(1704067200000.0)}
        )
        is True
    )


# ---------------------------------------------------------------------------
# get_synced_file_state_map
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_map_prefers_connector_file_id_over_document_id(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")

    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(
        return_value={
            "aggregations": {
                "by_connector_file_id": {
                    "buckets": [
                        {
                            "key": "c::a",
                            "latest_modified": {"value": 1704067200000.0},
                            # S3 hands back quoted tags; the helper normalizes.
                            "etag": {"buckets": [{"key": '"abc123"'}]},
                        },
                        # connector_file_id present but neither signal stored → both None
                        {
                            "key": "c::b",
                            "latest_modified": {"value": None},
                            "etag": {"buckets": []},
                        },
                    ]
                },
                "by_document_id": {
                    "buckets": [
                        # Langflow-path id (document_id holds the connector source id).
                        {"key": "c::lf", "latest_modified": {"value": 1704153600000.0}},
                        # A content-hash document_id from the standard path — harmless,
                        # never matches an enumerated source id. Overlaid/ignored.
                        {"key": "c::a", "latest_modified": {"value": 999.0}},
                    ]
                },
            }
        }
    )
    sm = MagicMock()
    sm.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    result = await connectors_api.get_synced_file_state_map(
        connector_type="azure_blob",
        user_id="alice",
        session_manager=sm,
        jwt_token=None,
    )

    # connector_file_id wins for c::a (1704067200000, not the 999 from document_id).
    assert result["c::a"].modified_time_ms == 1704067200000.0
    assert result["c::a"].content_etag == "abc123"
    assert result["c::b"].modified_time_ms is None
    assert result["c::b"].content_etag is None
    assert result["c::lf"].modified_time_ms == 1704153600000.0


# A terms agg on an analyzed `text` field raises; one on a field the index does
# not have returns no buckets and no error. So a field may only be switched to
# its `.keyword` sub-field once an error has proven the drift, and the two
# fields have to be retried independently — switching both together silently
# empties whichever aggregation was fine.


def _text_field_error(field: str) -> Exception:
    """The error OpenSearch raises for a terms agg on an analyzed text field."""
    return Exception(
        "RequestError(400, 'search_phase_execution_exception', 'Text fields "
        "are not optimised for operations that require per-document field "
        "data like aggregations and sorting, so these operations are "
        "disabled by default. Please use a keyword field instead. "
        f"Alternatively, set fielddata=true on [{field}]...')"
    )


def _mapping_drift_client(text_mapped: set[str]):
    """Fake OpenSearch whose aggregations behave like a real index's mappings.

    Fields in ``text_mapped`` raise when aggregated directly (they are analyzed
    text). A `.keyword` sub-field only resolves for those; asking for it on a
    properly mapped field returns no buckets, exactly as OpenSearch does for a
    field that does not exist — which is what makes a speculative switch silent.

    Records every (id_field, etag_field) pair attempted.
    """
    attempts: list[tuple[str, str]] = []
    client = AsyncMock()

    async def fake_search(*, index, body):
        id_field = body["aggs"]["by_connector_file_id"]["terms"]["field"]
        etag_field = body["aggs"]["by_connector_file_id"]["aggs"]["etag"]["terms"]["field"]
        attempts.append((id_field, etag_field))
        for field in (id_field, etag_field):
            base = field.removesuffix(".keyword")
            if base in text_mapped and field == base:
                raise _text_field_error(base)
        etag_resolves = etag_field.removesuffix(".keyword") in text_mapped or (
            not etag_field.endswith(".keyword")
        )
        id_resolves = id_field.removesuffix(".keyword") in text_mapped or (
            not id_field.endswith(".keyword")
        )
        etag_buckets = [{"key": '"abc123"'}] if etag_resolves else []
        return {
            "aggregations": {
                "by_connector_file_id": {
                    "buckets": [
                        {
                            "key": "c::a",
                            "latest_modified": {"value": 1704067200000.0},
                            "etag": {"buckets": etag_buckets},
                        }
                    ]
                    if id_resolves
                    else []
                },
                "by_document_id": {"buckets": []},
            }
        }

    client.search = AsyncMock(side_effect=fake_search)
    return client, attempts


async def _state_map_with(monkeypatch, text_mapped: set[str]):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    client, attempts = _mapping_drift_client(text_mapped)
    sm = MagicMock()
    sm.get_user_opensearch_client = MagicMock(return_value=client)

    result = await connectors_api.get_synced_file_state_map(
        connector_type="ibm_cos",
        user_id="alice",
        session_manager=sm,
        jwt_token=None,
    )
    return result, attempts


@pytest.mark.asyncio
async def test_state_map_uses_plain_fields_when_nothing_has_drifted(monkeypatch):
    result, attempts = await _state_map_with(monkeypatch, text_mapped=set())

    assert attempts == [("connector_file_id", "content_etag")]
    assert result["c::a"].content_etag == "abc123"


@pytest.mark.asyncio
async def test_state_map_keeps_etags_on_an_index_predating_content_etag(monkeypatch):
    """The legacy case: connector_file_id drifted, content_etag did not.

    content_etag was added to the explicit mapping long after connector_file_id,
    so an index old enough to have the text-mapped id has a correctly mapped (or
    absent) content_etag with no `.keyword` sub-field. Retrying both fields
    together asks for content_etag.keyword, which resolves to nothing and drops
    every stored etag — silently regressing change detection to timestamps on
    exactly the indices that need it most.
    """
    result, attempts = await _state_map_with(monkeypatch, text_mapped={"connector_file_id"})

    assert attempts == [
        ("connector_file_id", "content_etag"),
        ("connector_file_id.keyword", "content_etag"),
    ]
    assert result["c::a"].modified_time_ms == 1704067200000.0
    assert result["c::a"].content_etag == "abc123"


@pytest.mark.asyncio
async def test_state_map_keeps_source_ids_when_only_content_etag_drifted(monkeypatch):
    """The inverse: switching connector_file_id too would empty the id buckets.

    With no source ids in the map every file classifies as unchanged, which is
    the original "overwrite in COS is not reflected" defect all over again.
    """
    result, attempts = await _state_map_with(monkeypatch, text_mapped={"content_etag"})

    assert attempts == [
        ("connector_file_id", "content_etag"),
        ("connector_file_id.keyword", "content_etag"),
        ("connector_file_id", "content_etag.keyword"),
    ]
    assert "c::a" in result
    assert result["c::a"].content_etag == "abc123"


@pytest.mark.asyncio
async def test_state_map_switches_both_fields_only_when_both_drifted(monkeypatch):
    result, attempts = await _state_map_with(
        monkeypatch, text_mapped={"connector_file_id", "content_etag"}
    )

    assert attempts[-1] == ("connector_file_id.keyword", "content_etag.keyword")
    assert result["c::a"].content_etag == "abc123"


@pytest.mark.asyncio
async def test_state_map_gives_up_after_exhausting_field_forms(monkeypatch):
    """An unmapped-keyword error no candidate can fix must surface, not hang."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    client = AsyncMock()
    client.search = AsyncMock(side_effect=_text_field_error("connector_file_id"))
    sm = MagicMock()
    sm.get_user_opensearch_client = MagicMock(return_value=client)

    # The outer handler converts a failed lookup into an empty map (backfill-safe).
    result = await connectors_api.get_synced_file_state_map(
        connector_type="ibm_cos",
        user_id="alice",
        session_manager=sm,
        jwt_token=None,
    )
    assert result == {}
    assert client.search.await_count == 4


@pytest.mark.asyncio
async def test_state_map_returns_empty_on_error(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(side_effect=RuntimeError("boom"))
    sm = MagicMock()
    sm.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    result = await connectors_api.get_synced_file_state_map(
        connector_type="azure_blob",
        user_id="alice",
        session_manager=sm,
        jwt_token=None,
    )
    assert result == {}


# ---------------------------------------------------------------------------
# get_synced_id_to_filename_map
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filename_map_includes_connector_file_id_only_buckets(monkeypatch):
    """Regression test: filenames for ids that only exist under connector_file_id
    (the standard ConnectorFileProcessor path used by OAuth connectors, S3, etc.)
    must not be dropped just because document_id holds an unrelated content hash."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")

    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(
        return_value={
            "aggregations": {
                "by_connector_file_id": {
                    "buckets": [
                        {
                            "key": "gdrive-file-guid",
                            "top_filename": {"buckets": [{"key": "report.pdf"}]},
                        },
                    ]
                },
                "by_document_id": {
                    "buckets": [
                        # Content-hash document_id from the standard ingest path —
                        # unrelated to any enumerated source id.
                        {
                            "key": "content-hash-abc",
                            "top_filename": {"buckets": [{"key": "report.pdf"}]},
                        },
                    ]
                },
            }
        }
    )
    sm = MagicMock()
    sm.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    result = await connectors_api.get_synced_id_to_filename_map(
        connector_type="google_drive",
        user_id="alice",
        session_manager=sm,
        jwt_token=None,
    )

    assert result["gdrive-file-guid"] == "report.pdf"
    assert result["content-hash-abc"] == "report.pdf"


@pytest.mark.asyncio
async def test_filename_map_prefers_connector_file_id_over_document_id(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")

    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(
        return_value={
            "aggregations": {
                "by_connector_file_id": {
                    "buckets": [
                        {"key": "c::a", "top_filename": {"buckets": [{"key": "real-name.txt"}]}},
                    ]
                },
                "by_document_id": {
                    "buckets": [
                        # Same key from the content-hash side, stale/wrong filename —
                        # connector_file_id must win.
                        {"key": "c::a", "top_filename": {"buckets": [{"key": "stale-name.txt"}]}},
                    ]
                },
            }
        }
    )
    sm = MagicMock()
    sm.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    result = await connectors_api.get_synced_id_to_filename_map(
        connector_type="azure_blob",
        user_id="alice",
        session_manager=sm,
        jwt_token=None,
    )

    assert result["c::a"] == "real-name.txt"


@pytest.mark.asyncio
async def test_filename_map_falls_back_to_keyword_subfield_on_text_field_error(
    monkeypatch,
):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")

    opensearch_client = AsyncMock()
    called_fields = []

    async def fake_search(*, index, body):
        called_fields.append(body["aggs"]["by_connector_file_id"]["terms"]["field"])
        if len(called_fields) == 1:
            raise Exception(
                "RequestError(400, 'search_phase_execution_exception', 'Text fields "
                "are not optimised for operations that require per-document field "
                "data like aggregations and sorting, so these operations are "
                "disabled by default. Please use a keyword field instead. "
                "Alternatively, set fielddata=true on [connector_file_id]...')"
            )
        return {
            "aggregations": {
                "by_connector_file_id": {
                    "buckets": [
                        {"key": "c::a", "top_filename": {"buckets": [{"key": "real-name.txt"}]}},
                    ]
                },
                "by_document_id": {"buckets": []},
            }
        }

    opensearch_client.search = AsyncMock(side_effect=fake_search)
    sm = MagicMock()
    sm.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    result = await connectors_api.get_synced_id_to_filename_map(
        connector_type="azure_blob",
        user_id="alice",
        session_manager=sm,
        jwt_token=None,
    )

    assert result == {"c::a": "real-name.txt"}
    assert called_fields == ["connector_file_id", "connector_file_id.keyword"]


@pytest.mark.asyncio
async def test_filename_map_returns_empty_on_error(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(side_effect=RuntimeError("boom"))
    sm = MagicMock()
    sm.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    result = await connectors_api.get_synced_id_to_filename_map(
        connector_type="azure_blob",
        user_id="alice",
        session_manager=sm,
        jwt_token=None,
    )
    assert result == {}


# ---------------------------------------------------------------------------
# get_synced_file_ids_for_connector
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synced_file_ids_falls_back_to_keyword_subfield_on_text_field_error(
    monkeypatch,
):
    """Same text-field mapping-drift issue as get_synced_file_state_map,
    but here a fatal (uncaught) error would make orphan detection and bucket
    reconciliation treat every connector file as never-synced."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")

    opensearch_client = AsyncMock()
    called_fields = []

    async def fake_search(*, index, body):
        called_fields.append(body["aggs"]["unique_connector_file_ids"]["terms"]["field"])
        if len(called_fields) == 1:
            raise Exception(
                "RequestError(400, 'search_phase_execution_exception', 'Text fields "
                "are not optimised for operations that require per-document field "
                "data...set fielddata=true on [connector_file_id]...')"
            )
        return {
            "aggregations": {
                "unique_connector_file_ids": {"buckets": [{"key": "c::a"}]},
                "unique_document_ids": {"buckets": []},
                "unique_filenames": {"buckets": []},
            }
        }

    opensearch_client.search = AsyncMock(side_effect=fake_search)
    sm = MagicMock()
    sm.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    file_ids, filenames, id_field = await connectors_api.get_synced_file_ids_for_connector(
        connector_type="azure_blob",
        user_id="alice",
        session_manager=sm,
        jwt_token=None,
    )

    assert file_ids == ["c::a"]
    assert id_field == "connector_file_id"
    assert called_fields == ["connector_file_id", "connector_file_id.keyword"]


# ---------------------------------------------------------------------------
# connector_sync — bucket_filter reconciliation
# ---------------------------------------------------------------------------


def _bucket_sync_service(remote_files, task_id="task-x"):
    connection = SimpleNamespace(connection_id="conn-1", is_active=True)
    connector = MagicMock()
    connector.authenticate = AsyncMock(return_value=True)
    connector.bucket_names = None
    connector.list_files = AsyncMock(return_value={"files": remote_files, "next_page_token": None})

    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock(return_value=[connection])
    service.get_connector = AsyncMock(return_value=connector)
    service.sync_specific_files = AsyncMock(return_value=task_id)
    return service


@pytest.mark.asyncio
async def test_bucket_filter_ingests_only_new_and_changed(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    # "c::ingested_unchanged" and "c::ingested_changed" are already ingested.
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(
            return_value=(["c::ingested_unchanged", "c::ingested_changed"], [], "connector_file_id")
        ),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_state_map",
        AsyncMock(
            return_value={
                "c::ingested_unchanged": _stored(1704067200000.0),  # 2024-01-01
                "c::ingested_changed": _stored(1704067200000.0),  # 2024-01-01
            }
        ),
    )

    remote_files = [
        {"id": "c::new", "modified_time": "2024-01-01T00:00:00Z"},
        {"id": "c::ingested_unchanged", "modified_time": "2024-01-01T00:00:00Z"},
        {"id": "c::ingested_changed", "modified_time": "2024-06-01T00:00:00Z"},
    ]
    service = _bucket_sync_service(remote_files)

    response = await connectors_api.connector_sync(
        "azure_blob",
        connectors_api.ConnectorSyncBody(connection_id="conn-1", bucket_filter=["c"]),
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )

    assert response.status_code == 201
    assert _json(response)["task_ids"] == ["task-x", "task-x"]

    # Two batches: new (replace defaulted False) + changed (replace=True).
    assert service.sync_specific_files.await_count == 2
    new_call, changed_call = service.sync_specific_files.await_args_list
    assert new_call.args[2] == ["c::new"]
    assert new_call.kwargs.get("replace_duplicates", False) is False
    assert changed_call.args[2] == ["c::ingested_changed"]
    assert changed_call.kwargs["replace_duplicates"] is True


@pytest.mark.asyncio
async def test_bucket_filter_all_unchanged_returns_no_files(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["c::a", "c::b"], [], "connector_file_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_state_map",
        AsyncMock(
            return_value={"c::a": _stored(1704067200000.0), "c::b": _stored(1704067200000.0)}
        ),
    )

    remote_files = [
        {"id": "c::a", "modified_time": "2024-01-01T00:00:00Z"},
        {"id": "c::b", "modified_time": "2024-01-01T00:00:00Z"},
    ]
    service = _bucket_sync_service(remote_files)

    response = await connectors_api.connector_sync(
        "azure_blob",
        connectors_api.ConnectorSyncBody(connection_id="conn-1", bucket_filter=["c"]),
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )

    assert response.status_code == 200
    body = _json(response)
    assert body["status"] == "no_files"
    assert "up to date" in body["message"]
    service.sync_specific_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_bucket_filter_only_new_files_single_batch(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=([], [], "connector_file_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_state_map",
        AsyncMock(return_value={}),
    )

    remote_files = [
        {"id": "c::a", "modified_time": "2024-01-01T00:00:00Z"},
        {"id": "c::b", "modified_time": "2024-01-01T00:00:00Z"},
    ]
    service = _bucket_sync_service(remote_files)

    response = await connectors_api.connector_sync(
        "azure_blob",
        connectors_api.ConnectorSyncBody(connection_id="conn-1", bucket_filter=["c"]),
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )

    assert response.status_code == 201
    service.sync_specific_files.assert_awaited_once()
    call = service.sync_specific_files.await_args
    assert call.args[2] == ["c::a", "c::b"]
    assert call.kwargs.get("replace_duplicates", False) is False


# ---------------------------------------------------------------------------
# bucket_changed_file_ids — updates-only change detection helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bucket_changed_file_ids_filters_to_changed_ingested(monkeypatch):
    """Only already-ingested blobs that are newer at source are returned; new
    (un-ingested) blobs are ignored (updates-only)."""
    from api import connectors as connectors_api

    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_state_map",
        AsyncMock(
            return_value={
                "c::a": _stored(1704067200000.0),
                "c::b": _stored(1704067200000.0),
            }  # 2024-01-01
        ),
    )

    connector = MagicMock()
    connector.list_files = AsyncMock(
        return_value={
            "files": [
                {"id": "c::a", "modified_time": "2024-01-01T00:00:00Z"},  # unchanged
                {"id": "c::b", "modified_time": "2024-06-01T00:00:00Z"},  # changed
                {"id": "c::new", "modified_time": "2024-06-01T00:00:00Z"},  # new → ignored
            ],
            "next_page_token": None,
        }
    )

    changed = await connectors_api.bucket_changed_file_ids(
        connector,
        "azure_blob",
        "alice",
        MagicMock(),
        "token",
        ["c::a", "c::b"],
    )
    assert changed == ["c::b"]


@pytest.mark.asyncio
async def test_bucket_changed_file_ids_detects_overwrite_by_etag(monkeypatch):
    """An overwritten object is caught by its entity tag alone.

    This is the case the timestamp check cannot see: nothing was stored to
    compare against (the file predates change detection, or an ingest path
    didn't persist the timestamp), so the file would report "unchanged" forever.
    """
    from api import connectors as connectors_api

    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_state_map",
        AsyncMock(
            return_value={
                "c::a": _stored(None, "etag-a"),
                "c::b": _stored(None, "etag-b"),
            }
        ),
    )

    connector = MagicMock()
    connector.list_files = AsyncMock(
        return_value={
            "files": [
                {"id": "c::a", "modified_time": None, "etag": "etag-a"},  # untouched
                {"id": "c::b", "modified_time": None, "etag": "etag-b-v2"},  # overwritten
            ],
            "next_page_token": None,
        }
    )

    changed = await connectors_api.bucket_changed_file_ids(
        connector, "ibm_cos", "alice", MagicMock(), "token", ["c::a", "c::b"]
    )
    assert changed == ["c::b"]


@pytest.mark.asyncio
async def test_bucket_changed_file_ids_warns_about_undetectable_files(monkeypatch):
    """Files with nothing to compare are reported, not silently called up to date."""
    from api import connectors as connectors_api

    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_state_map",
        AsyncMock(return_value={"c::a": _stored(), "c::b": _stored(1704067200000.0)}),
    )

    connector = MagicMock()
    connector.list_files = AsyncMock(
        return_value={
            "files": [
                # Ingested before any signal was recorded, and the listing has
                # no etag either — a modification here is unknowable.
                {"id": "c::a", "modified_time": "2024-06-01T00:00:00Z"},
                {"id": "c::b", "modified_time": "2024-01-01T00:00:00Z"},
            ],
            "next_page_token": None,
        }
    )

    # The project logger writes straight to stderr rather than propagating to the
    # stdlib root logger, so assert on the call instead of on caplog.
    warnings = []
    monkeypatch.setattr(
        connectors_api.logger,
        "warning",
        lambda msg, **kw: warnings.append((msg, kw)),
    )

    changed = await connectors_api.bucket_changed_file_ids(
        connector, "ibm_cos", "alice", MagicMock(), "token", ["c::a", "c::b"]
    )

    assert changed == []
    assert len(warnings) == 1
    msg, fields = warnings[0]
    assert "no stored change-detection signal" in msg
    assert fields["count"] == 1
    # c::b has a comparable timestamp — it is genuinely unchanged, not unknowable.
    assert fields["sample"] == ["c::a"]


@pytest.mark.asyncio
async def test_bucket_changed_file_ids_empty_when_no_existing():
    from api import connectors as connectors_api

    connector = MagicMock()
    connector.list_files = AsyncMock()
    changed = await connectors_api.bucket_changed_file_ids(
        connector, "azure_blob", "alice", MagicMock(), "token", []
    )
    assert changed == []
    connector.list_files.assert_not_awaited()


# ---------------------------------------------------------------------------
# connector_sync (Sync button, no selected_files/sync_all/bucket_filter) —
# updates-only re-ingest for bucket connectors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_button_bucket_reingests_only_changed(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["c::a", "c::b"], [], "connector_file_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "reconcile_orphans_for_connector_type",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_state_map",
        AsyncMock(
            return_value={"c::a": _stored(1704067200000.0), "c::b": _stored(1704067200000.0)}
        ),
    )

    remote_files = [
        {"id": "c::a", "modified_time": "2024-01-01T00:00:00Z"},  # unchanged
        {"id": "c::b", "modified_time": "2024-06-01T00:00:00Z"},  # changed
    ]
    service = _bucket_sync_service(remote_files)

    response = await connectors_api.connector_sync(
        "azure_blob",
        connectors_api.ConnectorSyncBody(),  # plain Sync: no files, no sync_all/bucket_filter
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )

    assert response.status_code == 201
    service.sync_specific_files.assert_awaited_once()
    call = service.sync_specific_files.await_args
    assert call.args[2] == ["c::b"]
    assert call.kwargs["replace_duplicates"] is True


@pytest.mark.asyncio
async def test_sync_button_bucket_all_unchanged_returns_no_files(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["c::a", "c::b"], [], "connector_file_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "reconcile_orphans_for_connector_type",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_state_map",
        AsyncMock(
            return_value={"c::a": _stored(1704067200000.0), "c::b": _stored(1704067200000.0)}
        ),
    )

    remote_files = [
        {"id": "c::a", "modified_time": "2024-01-01T00:00:00Z"},
        {"id": "c::b", "modified_time": "2024-01-01T00:00:00Z"},
    ]
    service = _bucket_sync_service(remote_files)

    response = await connectors_api.connector_sync(
        "azure_blob",
        connectors_api.ConnectorSyncBody(),
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )

    assert response.status_code == 200
    body = _json(response)
    assert body["status"] == "no_files"
    assert "up to date" in body["message"]
    service.sync_specific_files.assert_not_awaited()


# ---------------------------------------------------------------------------
# sync_all_connectors — updates-only re-ingest for bucket connectors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_all_bucket_reingests_only_changed(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(
        connectors_api,
        "_allowed_connector_types_for_request",
        AsyncMock(return_value=["azure_blob"]),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["c::a", "c::b"], [], "connector_file_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "reconcile_orphans_for_connector_type",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_state_map",
        AsyncMock(
            return_value={"c::a": _stored(1704067200000.0), "c::b": _stored(1704067200000.0)}
        ),
    )

    remote_files = [
        {"id": "c::a", "modified_time": "2024-01-01T00:00:00Z"},  # unchanged
        {"id": "c::b", "modified_time": "2024-06-01T00:00:00Z"},  # changed
    ]
    service = _bucket_sync_service(remote_files)

    response = await connectors_api.sync_all_connectors(
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )

    assert response.status_code == 201
    service.sync_specific_files.assert_awaited_once()
    call = service.sync_specific_files.await_args
    assert call.args[2] == ["c::b"]
    assert call.kwargs["replace_duplicates"] is True
