"""Duplicate handling for whole-container (bucket_filter) connector ingests.

The bug these cover: the pre-check that decides whether the overwrite dialog
appears was id-based only — "did THIS connector type already ingest this
blob?" — while the per-file backstop in ConnectorFileProcessor is filename-based
across every source. A bucket whose blobs share names with files ingested by
direct upload therefore reported zero duplicates, skipped the dialog, and had
every colliding file skipped at ingest time with "A file with this name already
exists". The two altitudes now ask the same question, and an overwrite
confirmed in the dialog reaches the bucket sync path.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _json(response):
    return json.loads(response.body.decode())


def _rbac_allowing(*perms: str):
    """RBAC stub granting exactly `perms` (unit tests run with enforcement on)."""
    rbac = MagicMock()
    granted = set(perms)

    async def has_permission(user_id, perm, role_override=None):
        return perm in granted

    rbac.has_permission = AsyncMock(side_effect=has_permission)
    return rbac


def _session_manager_finding(*indexed_filenames: str, synced_ids: tuple[str, ...] = ()):
    """Session manager whose OpenSearch client reports these filenames indexed,
    and these blob ids already synced under the connector.

    Serves both queries the sync issues for real — the filename terms
    aggregation behind find_existing_filenames, and the per-id lookup that asks
    which of those blobs this connector already ingested — so the real query
    paths run rather than a stubbed-out classifier.
    """
    indexed = set(indexed_filenames)
    synced = set(synced_ids)
    client = AsyncMock()

    async def search(*, index, body):
        terms = body["query"].get("terms")
        if terms is not None:
            asked = terms["filename"]
            return {
                "aggregations": {
                    "filenames": {"buckets": [{"key": name} for name in asked if name in indexed]}
                }
            }

        # The per-id "already synced here?" lookup.
        should = body["query"]["bool"]["filter"][1]["bool"]["should"]
        asked_ids = should[1]["terms"]["connector_file_id"]
        return {
            "aggregations": {
                "connector_file_ids": {
                    "buckets": [{"key": fid} for fid in asked_ids if fid in synced]
                },
                "document_ids": {"buckets": []},
            }
        }

    client.search = AsyncMock(side_effect=search)
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=client)
    return session_manager, client


def _bucket_connector(remote_files):
    connector = MagicMock()
    connector.authenticate = AsyncMock(return_value=True)
    connector.bucket_names = None
    connector.list_files = AsyncMock(return_value={"files": remote_files, "next_page_token": None})
    return connector


def _bucket_sync_service(remote_files, task_id="task-x"):
    connection = SimpleNamespace(connection_id="conn-1", is_active=True)
    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock(return_value=[connection])
    service.get_connector = AsyncMock(return_value=_bucket_connector(remote_files))
    service.sync_specific_files = AsyncMock(return_value=task_id)
    return service


# ---------------------------------------------------------------------------
# _classify_bucket_connector_duplicates — what the confirm dialog is told
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filename_indexed_by_another_source_is_a_duplicate(monkeypatch):
    """The reported bug: sample.pdf was uploaded directly, so no COS id matches
    it, but its name is taken. Without this the dialog never opened."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=([], [], "connector_file_id")),
    )
    session_manager, _ = _session_manager_finding("sample.pdf")

    result = await connectors_api._classify_bucket_connector_duplicates(
        connector=_bucket_connector(
            [
                {"id": "b::sample.pdf", "name": "sample.pdf"},
                {"id": "b::fresh.pdf", "name": "fresh.pdf"},
            ]
        ),
        connector_type="ibm_cos",
        bucket_filter=["b"],
        session_manager=session_manager,
        user_id="alice",
        jwt_token="token",
    )

    assert result["duplicate_count"] == 1
    assert result["duplicate_names"] == ["sample.pdf"]
    assert [f["id"] for f in result["non_duplicate_files"]] == ["b::fresh.pdf"]
    assert result["total_files"] == 2


@pytest.mark.asyncio
async def test_already_synced_id_is_still_a_duplicate(monkeypatch):
    """The id half of the check survives: a blob this connector ingested before
    counts even when its indexed chunks are invisible to the filename lookup."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["b::already.pdf"], [], "connector_file_id")),
    )
    session_manager, _ = _session_manager_finding()

    result = await connectors_api._classify_bucket_connector_duplicates(
        connector=_bucket_connector(
            [
                {"id": "b::already.pdf", "name": "already.pdf"},
                {"id": "b::fresh.pdf", "name": "fresh.pdf"},
            ]
        ),
        connector_type="ibm_cos",
        bucket_filter=["b"],
        session_manager=session_manager,
        user_id="alice",
        jwt_token="token",
    )

    assert result["duplicate_names"] == ["already.pdf"]
    assert [f["id"] for f in result["non_duplicate_files"]] == ["b::fresh.pdf"]


@pytest.mark.asyncio
async def test_alias_match_counts_as_duplicate(monkeypatch):
    """Legacy Langflow ingest indexes notes.txt as notes.md — the alias the
    processor backstop also honors."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=([], [], "connector_file_id")),
    )
    session_manager, _ = _session_manager_finding("notes.md")

    result = await connectors_api._classify_bucket_connector_duplicates(
        connector=_bucket_connector([{"id": "b::notes.txt", "name": "notes.txt"}]),
        connector_type="ibm_cos",
        bucket_filter=["b"],
        session_manager=session_manager,
        user_id="alice",
        jwt_token="token",
    )

    assert result["duplicate_names"] == ["notes.txt"]


@pytest.mark.asyncio
async def test_nothing_indexed_reports_no_duplicates(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=([], [], "connector_file_id")),
    )
    session_manager, _ = _session_manager_finding()

    result = await connectors_api._classify_bucket_connector_duplicates(
        connector=_bucket_connector([{"id": "b::a.pdf", "name": "a.pdf"}]),
        connector_type="ibm_cos",
        bucket_filter=["b"],
        session_manager=session_manager,
        user_id="alice",
        jwt_token="token",
    )

    assert result["duplicate_count"] == 0
    assert [f["id"] for f in result["non_duplicate_files"]] == ["b::a.pdf"]


@pytest.mark.asyncio
async def test_missing_index_is_not_an_error(monkeypatch):
    """First ingest on a fresh instance: no documents index yet, nothing is a
    duplicate. Any other search failure still propagates."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=([], [], "connector_file_id")),
    )
    client = AsyncMock()
    client.search = AsyncMock(side_effect=Exception("index_not_found_exception: idx"))
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=client)

    result = await connectors_api._classify_bucket_connector_duplicates(
        connector=_bucket_connector([{"id": "b::a.pdf", "name": "a.pdf"}]),
        connector_type="ibm_cos",
        bucket_filter=["b"],
        session_manager=session_manager,
        user_id="alice",
        jwt_token="token",
    )

    assert result["duplicate_count"] == 0


# ---------------------------------------------------------------------------
# connector_sync — what "overwrite" does to a whole-container selection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bucket_filter_overwrite_replaces_only_the_colliding_files(monkeypatch):
    """Overwrite targets the blobs whose name is indexed but which this
    connector never synced. Nothing we store about them can say whether the
    source is newer, so change detection cannot decide them — they are replaced
    outright, while a blob this connector already synced and that has not
    changed is still skipped."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["b::synced.pdf"], [], "connector_file_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_state_map",
        AsyncMock(
            return_value={
                "b::synced.pdf": connectors_api.SyncedFileState(
                    modified_time_ms=1704067200000.0, content_etag=None
                )
            }
        ),
    )

    remote_files = [
        # Uploaded directly before this connector existed: name taken, id new.
        {"id": "b::uploaded.pdf", "name": "uploaded.pdf", "modified_time": "2024-01-01T00:00:00Z"},
        # Synced by this connector and unchanged at source.
        {"id": "b::synced.pdf", "name": "synced.pdf", "modified_time": "2024-01-01T00:00:00Z"},
        # Not indexed anywhere.
        {"id": "b::fresh.pdf", "name": "fresh.pdf", "modified_time": "2024-01-01T00:00:00Z"},
    ]
    service = _bucket_sync_service(remote_files)
    session_manager, _ = _session_manager_finding(
        "uploaded.pdf", "synced.pdf", synced_ids=("b::synced.pdf",)
    )

    response = await connectors_api.connector_sync(
        "ibm_cos",
        connectors_api.ConnectorSyncBody(
            connection_id="conn-1", bucket_filter=["b"], replace_duplicates=True
        ),
        request=MagicMock(),
        connector_service=service,
        session_manager=session_manager,
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )

    assert response.status_code == 201
    assert service.sync_specific_files.await_count == 2
    new_call, replace_call = service.sync_specific_files.await_args_list
    assert new_call.args[2] == ["b::fresh.pdf"]
    assert new_call.kwargs.get("replace_duplicates", False) is False
    # Only the name collision is overwritten; the unchanged synced blob is not
    # in either batch.
    assert replace_call.args[2] == ["b::uploaded.pdf"]
    assert replace_call.kwargs["replace_duplicates"] is True


@pytest.mark.asyncio
async def test_bucket_filter_overwrite_batches_collisions_with_changed_blobs(monkeypatch):
    """A blob changed at source and a blob colliding by name both need the same
    replace semantics, so they ride in one batch."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["b::changed.pdf"], [], "connector_file_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_state_map",
        AsyncMock(
            return_value={
                "b::changed.pdf": connectors_api.SyncedFileState(
                    modified_time_ms=1704067200000.0, content_etag=None
                )
            }
        ),
    )

    remote_files = [
        {"id": "b::uploaded.pdf", "name": "uploaded.pdf", "modified_time": "2024-01-01T00:00:00Z"},
        {"id": "b::changed.pdf", "name": "changed.pdf", "modified_time": "2024-06-01T00:00:00Z"},
    ]
    service = _bucket_sync_service(remote_files)
    session_manager, _ = _session_manager_finding(
        "uploaded.pdf", "changed.pdf", synced_ids=("b::changed.pdf",)
    )

    await connectors_api.connector_sync(
        "ibm_cos",
        connectors_api.ConnectorSyncBody(
            connection_id="conn-1", bucket_filter=["b"], replace_duplicates=True
        ),
        request=MagicMock(),
        connector_service=service,
        session_manager=session_manager,
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )

    assert service.sync_specific_files.await_count == 1
    call = service.sync_specific_files.await_args
    assert sorted(call.args[2]) == ["b::changed.pdf", "b::uploaded.pdf"]
    assert call.kwargs["replace_duplicates"] is True


@pytest.mark.asyncio
async def test_bucket_filter_without_overwrite_never_looks_up_filenames(monkeypatch):
    """Declining the overwrite leaves the sync exactly as it was: the colliding
    blob rides in the plain batch and the processor backstop skips it. No
    filename lookup is issued."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=([], [], "connector_file_id")),
    )
    monkeypatch.setattr(connectors_api, "get_synced_file_state_map", AsyncMock(return_value={}))

    remote_files = [
        {"id": "b::uploaded.pdf", "name": "uploaded.pdf", "modified_time": "2024-01-01T00:00:00Z"}
    ]
    service = _bucket_sync_service(remote_files)
    session_manager, client = _session_manager_finding("uploaded.pdf")

    await connectors_api.connector_sync(
        "ibm_cos",
        connectors_api.ConnectorSyncBody(connection_id="conn-1", bucket_filter=["b"]),
        request=MagicMock(),
        connector_service=service,
        session_manager=session_manager,
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )

    client.search.assert_not_awaited()
    call = service.sync_specific_files.await_args
    assert call.args[2] == ["b::uploaded.pdf"]
    assert call.kwargs.get("replace_duplicates", False) is False


@pytest.mark.asyncio
async def test_bucket_filter_sync_carries_filenames_into_the_task(monkeypatch):
    """Without file_infos the task view shows the raw "<bucket>::<key>" id until
    each blob is fetched."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=([], [], "connector_file_id")),
    )
    monkeypatch.setattr(connectors_api, "get_synced_file_state_map", AsyncMock(return_value={}))

    remote_files = [
        {"id": "b::deep/report.pdf", "name": "report.pdf", "modified_time": None},
    ]
    service = _bucket_sync_service(remote_files)

    await connectors_api.connector_sync(
        "ibm_cos",
        connectors_api.ConnectorSyncBody(connection_id="conn-1", bucket_filter=["b"]),
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )

    file_infos = service.sync_specific_files.await_args.kwargs["file_infos"]
    assert [f["name"] for f in file_infos] == ["report.pdf"]
    assert [f["id"] for f in file_infos] == ["b::deep/report.pdf"]


@pytest.mark.asyncio
async def test_bucket_filter_listing_without_ids_starts_no_sync(monkeypatch):
    """Nothing addressable in the listing: report no_files rather than starting
    an empty task."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    service = _bucket_sync_service([{"name": "no-id.pdf"}])

    response = await connectors_api.connector_sync(
        "ibm_cos",
        connectors_api.ConnectorSyncBody(
            connection_id="conn-1", bucket_filter=["b"], replace_duplicates=True
        ),
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )

    assert response.status_code == 200
    assert _json(response)["status"] == "no_files"
    service.sync_specific_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_overwrite_gives_one_winner_when_two_blobs_share_a_name(monkeypatch):
    """A bucket connector names a blob after its key's basename, so a/report.pdf
    and b/report.pdf both land on "report.pdf". Files within a task are ingested
    concurrently, so letting both replace the same document has no defined
    winner. The first in listing order takes the name; the other rides in the
    plain batch, where the per-file backstop skips it as a duplicate.
    """
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=([], [], "connector_file_id")),
    )
    monkeypatch.setattr(connectors_api, "get_synced_file_state_map", AsyncMock(return_value={}))

    remote_files = [
        {"id": "b::a/report.pdf", "name": "report.pdf", "modified_time": None},
        {"id": "b::c/report.pdf", "name": "report.pdf", "modified_time": None},
    ]
    service = _bucket_sync_service(remote_files)
    session_manager, _ = _session_manager_finding("report.pdf")

    await connectors_api.connector_sync(
        "ibm_cos",
        connectors_api.ConnectorSyncBody(
            connection_id="conn-1", bucket_filter=["b"], replace_duplicates=True
        ),
        request=MagicMock(),
        connector_service=service,
        session_manager=session_manager,
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )

    assert service.sync_specific_files.await_count == 2
    new_call, replace_call = service.sync_specific_files.await_args_list
    assert replace_call.args[2] == ["b::a/report.pdf"]
    assert replace_call.kwargs["replace_duplicates"] is True
    assert new_call.args[2] == ["b::c/report.pdf"]
    assert new_call.kwargs.get("replace_duplicates", False) is False


@pytest.mark.asyncio
async def test_alias_collision_between_two_blobs_gets_one_winner(monkeypatch):
    """notes.txt and notes.md are ingestion aliases of one another, so two blobs
    can contest a name without sharing one."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=([], [], "connector_file_id")),
    )
    monkeypatch.setattr(connectors_api, "get_synced_file_state_map", AsyncMock(return_value={}))

    remote_files = [
        {"id": "b::notes.txt", "name": "notes.txt", "modified_time": None},
        {"id": "b::notes.md", "name": "notes.md", "modified_time": None},
    ]
    service = _bucket_sync_service(remote_files)
    session_manager, _ = _session_manager_finding("notes.md")

    await connectors_api.connector_sync(
        "ibm_cos",
        connectors_api.ConnectorSyncBody(
            connection_id="conn-1", bucket_filter=["b"], replace_duplicates=True
        ),
        request=MagicMock(),
        connector_service=service,
        session_manager=session_manager,
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )

    replace_calls = [
        c for c in service.sync_specific_files.await_args_list if c.kwargs.get("replace_duplicates")
    ]
    assert len(replace_calls) == 1
    assert replace_calls[0].args[2] == ["b::notes.txt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("granted", [True, False])
async def test_overwrite_carries_the_users_anonymous_delete_permission(monkeypatch, granted):
    """Replacing a duplicate can delete a shared (ownerless) document, which is
    what knowledge:delete:anonymous governs. connector_sync already resolves it
    for orphan cleanup; the sync must hand the same answer to the replace path
    rather than letting it widen on its own."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=([], [], "connector_file_id")),
    )
    monkeypatch.setattr(connectors_api, "get_synced_file_state_map", AsyncMock(return_value={}))

    remote_files = [{"id": "b::report.pdf", "name": "report.pdf", "modified_time": None}]
    service = _bucket_sync_service(remote_files)
    session_manager, _ = _session_manager_finding("report.pdf")

    await connectors_api.connector_sync(
        "ibm_cos",
        connectors_api.ConnectorSyncBody(
            connection_id="conn-1", bucket_filter=["b"], replace_duplicates=True
        ),
        request=MagicMock(),
        connector_service=service,
        session_manager=session_manager,
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous") if granted else _rbac_allowing(),
    )

    call = service.sync_specific_files.await_args
    assert call.kwargs["replace_duplicates"] is True
    assert call.kwargs["allow_anonymous_delete"] is granted


@pytest.mark.asyncio
async def test_overwrite_ignores_a_truncated_synced_id_listing(monkeypatch):
    """get_synced_file_ids_for_connector's terms aggregation is capped at
    OPENSEARCH_TERMS_AGG_LIMIT, so a container past the cap reports only some of
    the ids it has ingested. An omitted blob must not become a collision with
    its own indexed document and get re-ingested — the case that matters here is
    exactly the large container.
    """
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    # Truncated: the blob IS ingested, but the capped listing leaves it out.
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=([], [], "connector_file_id")),
    )
    monkeypatch.setattr(connectors_api, "get_synced_file_state_map", AsyncMock(return_value={}))

    remote_files = [{"id": "b::synced.pdf", "name": "synced.pdf", "modified_time": None}]
    service = _bucket_sync_service(remote_files)
    # The per-id lookup knows the truth the capped listing lost.
    session_manager, _ = _session_manager_finding("synced.pdf", synced_ids=("b::synced.pdf",))

    await connectors_api.connector_sync(
        "ibm_cos",
        connectors_api.ConnectorSyncBody(
            connection_id="conn-1", bucket_filter=["b"], replace_duplicates=True
        ),
        request=MagicMock(),
        connector_service=service,
        session_manager=session_manager,
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )

    # Not a collision: it falls through to change detection, which sees a blob
    # the truncated listing calls "new" and ingests it plainly — no replace.
    replace_calls = [
        c for c in service.sync_specific_files.await_args_list if c.kwargs.get("replace_duplicates")
    ]
    assert replace_calls == []


def _two_connection_service(remote_files, *, broken_first: bool = False):
    """Two active connections of one type, in list order conn-1, conn-2.

    connector_check_duplicates resolves the requested id, so the sync has to
    resolve the same one or the dialog and the ingest describe different
    connections.
    """
    connections = [
        SimpleNamespace(connection_id="conn-1", is_active=True),
        SimpleNamespace(connection_id="conn-2", is_active=True),
    ]
    connectors = {}
    for conn in connections:
        connector = _bucket_connector(remote_files)
        connector.authenticate = AsyncMock(
            return_value=not (broken_first and conn.connection_id == "conn-1")
        )
        connectors[conn.connection_id] = connector

    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock(return_value=connections)
    service.get_connector = AsyncMock(side_effect=lambda cid: connectors[cid])
    service.sync_specific_files = AsyncMock(return_value="task-x")
    return service


async def _sync_with_connection(service, connection_id, monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=([], [], "connector_file_id")),
    )
    monkeypatch.setattr(connectors_api, "get_synced_file_state_map", AsyncMock(return_value={}))

    return await connectors_api.connector_sync(
        "ibm_cos",
        connectors_api.ConnectorSyncBody(connection_id=connection_id, bucket_filter=["b"]),
        request=MagicMock(),
        connector_service=service,
        session_manager=_session_manager_finding()[0],
        user=SimpleNamespace(user_id="alice", jwt_token="token", db_user_id="alice"),
        session=MagicMock(),
        rbac=_rbac_allowing("knowledge:delete:anonymous"),
    )


@pytest.mark.asyncio
async def test_sync_uses_the_requested_connection(monkeypatch):
    """Not merely the first that authenticates — conn-2 is second in list order."""
    remote_files = [{"id": "b::a.pdf", "name": "a.pdf", "modified_time": None}]
    service = _two_connection_service(remote_files)

    await _sync_with_connection(service, "conn-2", monkeypatch)

    assert service.sync_specific_files.await_args.args[0] == "conn-2"


@pytest.mark.asyncio
async def test_sync_without_a_requested_connection_takes_the_first_working(monkeypatch):
    remote_files = [{"id": "b::a.pdf", "name": "a.pdf", "modified_time": None}]
    service = _two_connection_service(remote_files)

    await _sync_with_connection(service, None, monkeypatch)

    assert service.sync_specific_files.await_args.args[0] == "conn-1"


@pytest.mark.asyncio
async def test_a_requested_connection_that_cannot_authenticate_falls_back(monkeypatch):
    """Ordering rather than hard selection: an unusable connection behaves as it
    did before, rather than failing later inside the connector."""
    remote_files = [{"id": "b::a.pdf", "name": "a.pdf", "modified_time": None}]
    service = _two_connection_service(remote_files, broken_first=True)

    await _sync_with_connection(service, "conn-1", monkeypatch)

    assert service.sync_specific_files.await_args.args[0] == "conn-2"
