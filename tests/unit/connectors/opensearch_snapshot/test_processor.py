"""Snapshot import task processor: success, failure, cancellation, re-import, delete."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio

from connectors.opensearch_snapshot import fields as fields_mod
from connectors.opensearch_snapshot import restore
from connectors.opensearch_snapshot import service as svc
from connectors.opensearch_snapshot.processor import SnapshotImportProcessor
from models.tasks import FileTask, TaskStatus, UploadTask

from ._support import (
    MAPPING,
    SAMPLES,
    SLUG,
    FakeStore,
    enable_feature,
    install_engine,
    install_services,
    load_import,
    make_session_factory,
    seed_import,
    seed_source,
)


@pytest_asyncio.fixture
async def env(monkeypatch):
    engine, factory = await make_session_factory()
    enable_feature(monkeypatch)
    os_client, src = install_services(monkeypatch, factory)
    store = FakeStore()
    rec = install_engine(monkeypatch, store)
    await seed_source(factory)
    yield type(
        "Env", (), {"factory": factory, "os": os_client, "src": src, "store": store, "rec": rec}
    )
    await engine.dispose()


def _tasks(import_id: str = "imp-1"):
    file_task = FileTask(file_path=import_id, status=TaskStatus.RUNNING)
    upload = UploadTask(task_id="t1", total_files=1, file_tasks={import_id: file_task})
    return upload, file_task


class StatusError(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status_code = status


class ProbeClient:
    """The owner's own OpenSearch client as the post-publish access probe sees it."""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.searches: list[str] = []

    async def search(self, index: str, body: dict):
        self.searches.append(index)
        if self.error is not None:
            raise self.error
        return {"hits": {"hits": []}}


class FakeSessionManager:
    def __init__(self, client: ProbeClient | None = None, error: Exception | None = None):
        self.client = client or ProbeClient()
        self.error = error
        self.requests: list[tuple] = []

    def get_user_opensearch_client(self, user_id, jwt_token=None):
        self.requests.append((user_id, jwt_token))
        if self.error is not None:
            raise self.error
        return self.client


def _processor(kind="import", **kwargs):
    if kind == "reimport":  # what start_reimport passes after admitting the snapshot
        kwargs.setdefault("snapshot_uuid", f"uuid-{kwargs.get('snapshot')}")
        kwargs.setdefault("session_manager", FakeSessionManager())
        kwargs.setdefault("jwt_token", "jwt-alice")
    return SnapshotImportProcessor(
        import_id=kwargs.pop("import_id", "imp-1"),
        kind=kind,
        user_id="alice",
        ingestion_timeout=kwargs.pop("ingestion_timeout", None),
        **kwargs,
    )


def _concretes(generation: int, count: int = 2) -> list[str]:
    return [f"ds_{SLUG}_{n}_g{generation}" for n in range(count)]


def install_cluster(env, monkeypatch, *, serving_generation: int = 1, count: int = 2):
    """Alias targets of a tiny cluster: ``_aliases`` applies atomically, deleting an index drops
    the aliases on it. ``on_publish(call_number, swaps, apply)`` scripts lost acknowledgements,
    rollback failures and cancellations; the default applies the swap."""
    cluster = SimpleNamespace(publishes=0, deleted=[], on_publish=None)
    for n in range(count):
        env.os.aliases[f"ds_{SLUG}_{n}"] = {f"ds_{SLUG}_{n}_g{serving_generation}": {"aliases": {}}}

    def apply(swaps):
        for alias, new, old in swaps:
            targets = env.os.aliases.setdefault(alias, {})
            if old:
                targets.pop(old, None)
            targets[new] = {"aliases": {}}

    async def publish_aliases(os_admin, swaps):
        cluster.publishes += 1
        env.rec.calls.append(("publish_aliases", [tuple(s) for s in swaps]))
        if cluster.on_publish is None:
            apply(swaps)
        else:
            await cluster.on_publish(cluster.publishes, swaps, apply)

    async def delete_indices(os_admin, names):
        env.rec.calls.append(("delete_indices", list(names)))
        cluster.deleted.extend(names)
        for targets in env.os.aliases.values():
            for name in names:
                targets.pop(name, None)

    monkeypatch.setattr(restore, "publish_aliases", publish_aliases)
    monkeypatch.setattr(restore, "delete_indices", delete_indices)
    cluster.targets = lambda alias: set(env.os.aliases.get(alias, {}))
    return cluster


async def _set_import(env, **values):
    from db.repositories import SnapshotImportRepo

    async with env.factory() as session:
        await SnapshotImportRepo(session).update_import("imp-1", **values)
        await session.commit()


# ── initial import ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_initial_import_success_moves_to_review_with_suggested_field_maps(env):
    await seed_import(env.factory, status="staging", job_state="queued", field_map={})
    upload, file_task = _tasks()

    await _processor().process_item(upload, "imp-1", file_task)

    imp, datasets = await load_import(env.factory)
    assert (imp.status, imp.job_state, imp.job_error, imp.generation) == ("review", "idle", None, 1)
    assert imp.staged_bytes == env.store.stage_bytes
    expected_map = fields_mod.suggest_field_map(list(fields_mod.flatten_mapping(MAPPING)), SAMPLES)
    assert [d.concrete_index for d in datasets] == _concretes(1)
    assert all(d.doc_count == 42 and d.field_map == expected_map for d in datasets)

    rec = env.rec
    assert [c[1] for c in rec.names("restore_index")] == _concretes(1)
    assert [c[2] for c in rec.names("restore_index")] == ["idx_a", "idx_b"]
    # one repository, one alias publication for both datasets, aliases start fresh
    assert [c[1] for c in rec.names("register_repository")] == [f"openrag_stage_{SLUG}_g1"]
    assert rec.names("publish_aliases") == [
        (
            "publish_aliases",
            [(f"ds_{SLUG}_0", f"ds_{SLUG}_0_g1", None), (f"ds_{SLUG}_1", f"ds_{SLUG}_1_g1", None)],
        )
    ]
    # staged files and repository registration are removed once the data is restored
    assert ("delete_repository", f"openrag_stage_{SLUG}_g1") in rec.calls
    assert (SLUG, 1) in env.store.removed

    assert file_task.status == TaskStatus.COMPLETED
    assert (upload.successful_files, upload.failed_files) == (1, 0)
    assert file_task.result["datasets"] == 2


@pytest.mark.asyncio
async def test_initial_import_restore_failure_marks_failed_and_cleans_up(env):
    await seed_import(env.factory, status="staging", job_state="queued")
    env.rec.restore_failures["idx_b"] = restore.RestoreError("index is red: analyzer failed")
    upload, file_task = _tasks()

    await _processor().process_item(upload, "imp-1", file_task)

    imp, datasets = await load_import(env.factory)
    assert (imp.status, imp.job_state) == ("failed", "failed")
    assert "analyzer failed" in imp.job_error
    assert env.rec.names("publish_aliases") == []
    assert ("delete_indices", _concretes(1)) in env.rec.calls
    assert ("delete_repository", f"openrag_stage_{SLUG}_g1") in env.rec.calls
    assert (SLUG, 1) in env.store.removed
    assert (file_task.status, upload.failed_files) == (TaskStatus.FAILED, 1)


@pytest.mark.asyncio
async def test_unexpected_errors_are_not_leaked_to_the_job_error(env):
    await seed_import(env.factory, status="staging", job_state="queued")
    env.rec.restore_failures["idx_a"] = RuntimeError("AKIASECRETKEY in traceback")
    upload, file_task = _tasks()

    await _processor().process_item(upload, "imp-1", file_task)

    imp, _ = await load_import(env.factory)
    assert imp.status == "failed"
    assert "AKIA" not in imp.job_error and "AKIA" not in file_task.error


@pytest.mark.asyncio
async def test_cancellation_runs_shielded_cleanup_and_records_cancelled(env):
    await seed_import(env.factory, status="staging", job_state="queued")
    env.rec.restore_gate = asyncio.Event()  # restore blocks until cancelled
    upload, file_task = _tasks()

    job = asyncio.create_task(_processor().process_item(upload, "imp-1", file_task))
    for _ in range(200):
        if env.rec.names("restore_index"):
            break
        await asyncio.sleep(0.01)
    assert env.rec.names("restore_index")
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job

    imp, _ = await load_import(env.factory)
    assert (imp.status, imp.job_state) == ("failed", "cancelled")
    assert ("delete_indices", _concretes(1)) in env.rec.calls
    assert ("delete_repository", f"openrag_stage_{SLUG}_g1") in env.rec.calls
    assert (SLUG, 1) in env.store.removed
    assert (file_task.status, upload.failed_files) == (TaskStatus.FAILED, 1)


@pytest.mark.asyncio
async def test_timeout_fails_the_job_and_cleans_up(env, monkeypatch):
    await seed_import(env.factory, status="staging", job_state="queued")
    env.rec.restore_gate = asyncio.Event()
    processor = _processor(ingestion_timeout=3600)
    monkeypatch.setattr(
        processor, "_compute_deadline", lambda: asyncio.get_running_loop().time() + 0.05
    )
    upload, file_task = _tasks()

    await processor.process_item(upload, "imp-1", file_task)  # must not raise

    imp, _ = await load_import(env.factory)
    assert (imp.status, imp.job_state) == ("failed", "failed")
    assert "timed out" in imp.job_error
    assert ("delete_indices", _concretes(1)) in env.rec.calls
    assert file_task.status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_no_opensearch_security_calls_under_skip(env, monkeypatch):
    """FakeOS is strict: any role/mapping write (or any unexpected call) fails the test."""
    enable_feature(monkeypatch, skip_security=True)
    await seed_import(env.factory, status="staging", job_state="queued", shared=True)
    upload, file_task = _tasks()

    await _processor().process_item(upload, "imp-1", file_task)

    imp, _ = await load_import(env.factory)
    assert imp.status == "review"
    assert not [c for c in env.os.calls if "security" in str(c).lower()]


# ── re-import ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reimport_publishes_all_aliases_once_and_keeps_confirmed_field_maps(env):
    confirmed = {"text_fields": ["body"], "title_field": "title", "url_field": None}
    await seed_import(
        env.factory, status="active", job_state="queued", job_kind="reimport", field_map=confirmed
    )
    upload, file_task = _tasks()

    await _processor("reimport", snapshot="snap-2", written_by_version="3.9.0").process_item(
        upload, "imp-1", file_task
    )

    imp, datasets = await load_import(env.factory)
    assert (imp.status, imp.job_state, imp.generation) == ("active", "idle", 2)
    assert (imp.snapshot_name, imp.snapshot_uuid, imp.written_by_version) == (
        "snap-2",
        "uuid-snap-2",
        "3.9.0",
    )
    assert [d.concrete_index for d in datasets] == _concretes(2)
    assert all(d.field_map == confirmed and d.doc_count == 42 for d in datasets)

    publishes = env.rec.names("publish_aliases")
    assert publishes == [
        (
            "publish_aliases",
            [
                (f"ds_{SLUG}_0", f"ds_{SLUG}_0_g2", f"ds_{SLUG}_0_g1"),
                (f"ds_{SLUG}_1", f"ds_{SLUG}_1_g2", f"ds_{SLUG}_1_g1"),
            ],
        )
    ]
    # the old generation is deleted only after publication
    order = [c[0] for c in env.rec.calls]
    assert order.index("publish_aliases") < order.index("delete_indices")
    assert ("delete_indices", _concretes(1)) in env.rec.calls
    assert (SLUG, 2) in env.store.removed


@pytest.mark.asyncio
async def test_failed_reimport_keeps_previous_generation_active_and_aliases_untouched(env):
    await seed_import(env.factory, status="active", job_state="queued", job_kind="reimport")
    env.rec.restore_failures["idx_b"] = restore.RestoreError("not enough disk")
    upload, file_task = _tasks()

    await _processor("reimport", snapshot="snap-2").process_item(upload, "imp-1", file_task)

    imp, datasets = await load_import(env.factory)
    assert (imp.status, imp.generation, imp.job_state) == ("active", 1, "failed")
    assert "not enough disk" in imp.job_error
    assert [d.concrete_index for d in datasets] == _concretes(1)
    assert env.rec.names("publish_aliases") == []
    # only the *new* generation is removed; the serving indices are never named
    deleted = [name for c in env.rec.names("delete_indices") for name in c[1]]
    assert deleted == _concretes(2)
    assert (SLUG, 2) in env.store.removed and (SLUG, 1) not in env.store.removed


@pytest.mark.asyncio
async def test_reimport_with_incompatible_field_map_fails_before_publishing(env):
    await seed_import(env.factory, status="active", job_state="queued", job_kind="reimport")
    env.rec.mappings = {"properties": {"headline": {"type": "text"}}}  # title/body/url gone
    upload, file_task = _tasks()

    await _processor("reimport", snapshot="snap-2").process_item(upload, "imp-1", file_task)

    imp, datasets = await load_import(env.factory)
    assert (imp.status, imp.generation, imp.job_state) == ("active", 1, "failed")
    assert "field_map_incompatible" in imp.job_error
    assert env.rec.names("publish_aliases") == []
    assert [d.concrete_index for d in datasets] == _concretes(1)


@pytest.mark.asyncio
async def test_commit_failure_after_publish_swaps_aliases_back_then_deletes_new_generation(
    env, monkeypatch
):
    await seed_import(env.factory, status="active", job_state="queued", job_kind="reimport")

    async def broken_commit(self, *args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(SnapshotImportProcessor, "_commit", broken_commit)
    upload, file_task = _tasks()

    await _processor("reimport", snapshot="snap-2").process_item(upload, "imp-1", file_task)

    forward, backward = env.rec.names("publish_aliases")
    assert forward[1][0] == (f"ds_{SLUG}_0", f"ds_{SLUG}_0_g2", f"ds_{SLUG}_0_g1")
    assert backward[1][0] == (f"ds_{SLUG}_0", f"ds_{SLUG}_0_g1", f"ds_{SLUG}_0_g2")
    order = [c[0] for c in env.rec.calls]
    assert order.index("delete_indices") > len(order) - 1 - order[::-1].index("publish_aliases")
    assert ("delete_indices", _concretes(2)) in env.rec.calls
    imp, datasets = await load_import(env.factory)
    assert (imp.status, imp.generation, imp.job_state) == ("active", 1, "failed")
    assert [d.concrete_index for d in datasets] == _concretes(1)


@pytest.mark.asyncio
async def test_reimport_cancellation_leaves_previous_generation_serving(env):
    await seed_import(env.factory, status="active", job_state="queued", job_kind="reimport")
    env.rec.restore_gate = asyncio.Event()
    upload, file_task = _tasks()

    job = asyncio.create_task(
        _processor("reimport", snapshot="snap-2").process_item(upload, "imp-1", file_task)
    )
    for _ in range(200):
        if env.rec.names("restore_index"):
            break
        await asyncio.sleep(0.01)
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job

    imp, datasets = await load_import(env.factory)
    assert (imp.status, imp.generation, imp.job_state) == ("active", 1, "cancelled")
    assert [d.concrete_index for d in datasets] == _concretes(1)
    assert env.rec.names("publish_aliases") == []
    assert ("delete_indices", _concretes(2)) in env.rec.calls


# ── delete ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_job_removes_role_indices_repos_staging_and_rows(env, monkeypatch):
    enable_feature(
        monkeypatch, skip_security=True
    )  # roles.remove_role is a no-op; FakeOS is strict
    await seed_import(
        env.factory, status="deleting", job_state="queued", job_kind="delete", generation=2
    )
    upload, file_task = _tasks()

    await _processor("delete").process_item(upload, "imp-1", file_task)

    imp, datasets = await load_import(env.factory)
    assert imp is None and datasets == []
    assert ("delete_indices_for_slug", SLUG) in env.rec.calls
    repos = {c[1] for c in env.rec.names("delete_repository")}
    assert {f"openrag_stage_{SLUG}_g{g}" for g in (1, 2, 3)} <= repos
    assert (SLUG, None) in env.store.removed
    assert file_task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_job_cancelled_by_a_delete_leaves_the_delete_in_charge(env):
    await seed_import(env.factory, status="staging", job_state="queued")
    env.rec.restore_gate = asyncio.Event()
    upload, file_task = _tasks()

    job = asyncio.create_task(_processor().process_item(upload, "imp-1", file_task))
    for _ in range(200):
        if env.rec.names("restore_index"):
            break
        await asyncio.sleep(0.01)
    # what delete_import does before cancelling the task
    async with env.factory() as session:
        from db.repositories import SnapshotImportRepo

        await SnapshotImportRepo(session).update_import("imp-1", status="deleting")
        await session.commit()
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job

    imp, _ = await load_import(env.factory)
    assert imp.status == "deleting"  # not overwritten with "failed"
    assert ("delete_indices", _concretes(1)) in env.rec.calls  # artifacts still cleaned


@pytest.mark.asyncio
async def test_import_deleted_before_the_job_starts_does_nothing(env):
    await seed_import(env.factory, status="deleting", job_state="queued")
    upload, file_task = _tasks()

    await _processor().process_item(upload, "imp-1", file_task)

    assert env.rec.names("register_repository") == []
    assert env.store.staged == []
    assert file_task.status == TaskStatus.FAILED
    assert svc._reserved_bytes == {}


@pytest.mark.asyncio
async def test_partial_snapshots_restore_with_the_partial_flag(env):
    import dataclasses

    await seed_import(env.factory, status="staging", job_state="queued")
    original = env.src.list_snapshots

    async def partial_snapshots():
        return [dataclasses.replace(info, state="PARTIAL") for info in await original()]

    env.src.list_snapshots = partial_snapshots
    upload, file_task = _tasks()

    await _processor().process_item(upload, "imp-1", file_task)

    assert [c[-1] for c in env.rec.names("restore_index")] == [True, True]
    assert file_task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_successful_snapshots_restore_without_the_partial_flag(env):
    await seed_import(env.factory, status="staging", job_state="queued")
    upload, file_task = _tasks()

    await _processor().process_item(upload, "imp-1", file_task)

    assert [c[-1] for c in env.rec.names("restore_index")] == [False, False]


# ── publication recovery (B3, B4) ────────────────────────────────────────


def _alias(n: int) -> str:
    return f"ds_{SLUG}_{n}"


def _serving(cluster, generation: int, count: int = 2) -> bool:
    return all(cluster.targets(_alias(n)) == {f"ds_{SLUG}_{n}_g{generation}"} for n in range(count))


@pytest.mark.asyncio
async def test_lost_publication_ack_restores_old_aliases_before_deleting_the_new_generation(
    env, monkeypatch
):
    """B3: the server applied the atomic swap but the response never arrived."""
    await seed_import(env.factory, status="active", job_state="queued", job_kind="reimport")
    cluster = install_cluster(env, monkeypatch)
    intents = []

    async def lost_ack(call, swaps, apply):
        intents.append((await load_import(env.factory))[0].pending_publication)
        apply(swaps)  # the swap is applied server-side ...
        if call == 1:
            raise restore.RestoreError("connection reset")  # ... but no acknowledgement arrives

    cluster.on_publish = lost_ack
    upload, file_task = _tasks()

    await _processor("reimport", snapshot="snap-2").process_item(upload, "imp-1", file_task)

    # the publication intent was durable before the request went out
    assert intents[0] == {
        "generation": 2,
        "swaps": [[_alias(n), f"ds_{SLUG}_{n}_g2", f"ds_{SLUG}_{n}_g1"] for n in range(2)],
    }
    # real alias targets were inspected and pointed back before the new generation was deleted
    assert cluster.publishes == 2 and _serving(cluster, 1)
    order = [c[0] for c in env.rec.calls]
    assert order.index("delete_indices") > len(order) - 1 - order[::-1].index("publish_aliases")
    assert cluster.deleted == _concretes(2)
    imp, datasets = await load_import(env.factory)
    assert (imp.status, imp.generation, imp.job_state, imp.pending_publication) == (
        "active",
        1,
        "failed",
        None,
    )
    assert [d.concrete_index for d in datasets] == _concretes(1)


@pytest.mark.asyncio
async def test_cancellation_after_the_server_applied_the_swap_restores_the_old_aliases(
    env, monkeypatch
):
    await seed_import(env.factory, status="active", job_state="queued", job_kind="reimport")
    cluster = install_cluster(env, monkeypatch)
    applied = asyncio.Event()

    async def applied_then_hangs(call, swaps, apply):
        apply(swaps)
        if call == 1:
            applied.set()
            await asyncio.Event().wait()  # the response never comes; the job is cancelled here

    cluster.on_publish = applied_then_hangs
    upload, file_task = _tasks()

    job = asyncio.create_task(
        _processor("reimport", snapshot="snap-2").process_item(upload, "imp-1", file_task)
    )
    await asyncio.wait_for(applied.wait(), 5)
    assert not _serving(cluster, 1)  # the cluster really moved to the new generation
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job

    assert _serving(cluster, 1) and cluster.deleted == _concretes(2)
    imp, _ = await load_import(env.factory)
    assert (imp.status, imp.generation, imp.job_state, imp.pending_publication) == (
        "active",
        1,
        "cancelled",
        None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["reverse_publish", "alias_inspection"])
async def test_failed_alias_rollback_keeps_the_possibly_serving_generation_until_recovery(
    env, monkeypatch, failure
):
    """B4: a rollback that cannot be completed must never be followed by deleting the new indices."""
    await seed_import(env.factory, status="active", job_state="queued", job_kind="reimport")
    await _set_import(env, attempt_generation=2)  # what start_reimport reserves
    cluster = install_cluster(env, monkeypatch)
    real_get_alias = env.os.indices.get_alias
    broken = {"on": True}

    async def reverse_fails(call, swaps, apply):
        if call == 1 or not broken["on"]:
            apply(swaps)
        else:
            raise restore.RestoreError("opensearch unavailable")

    async def get_alias_fails(name):
        if broken["on"]:
            raise RuntimeError("opensearch unavailable")
        return await real_get_alias(name)

    if failure == "reverse_publish":
        cluster.on_publish = reverse_fails
    else:
        env.os.indices.get_alias = get_alias_fails

    async def broken_commit(self, *args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(SnapshotImportProcessor, "_commit", broken_commit)
    upload, file_task = _tasks()

    await _processor("reimport", snapshot="snap-2").process_item(upload, "imp-1", file_task)

    assert cluster.deleted == []  # nothing that may still serve an alias was deleted
    assert _serving(cluster, 2)
    assert (SLUG, 2) not in env.store.removed
    imp, datasets = await load_import(env.factory)
    assert (imp.status, imp.generation, imp.job_state) == ("active", 1, "recovery")
    assert imp.pending_publication["generation"] == 2
    assert [d.concrete_index for d in datasets] == _concretes(1)

    # recovery keeps failing while OpenSearch cannot be reconciled ...
    assert await svc.recover_import("imp-1") is False
    assert cluster.deleted == [] and (await load_import(env.factory))[0].job_state == "recovery"

    # ... and completes once it can: aliases back on the old generation, then the new one is removed
    broken["on"] = False
    assert await svc.recover_import("imp-1") is True
    assert _serving(cluster, 1) and cluster.deleted == _concretes(2)
    assert (SLUG, 2) in env.store.removed
    imp, _ = await load_import(env.factory)
    assert (imp.job_state, imp.pending_publication) == ("failed", None)


# ── re-import probe (B11) ────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "manager",
    [
        pytest.param(lambda: FakeSessionManager(ProbeClient(StatusError(401))), id="401"),
        pytest.param(lambda: FakeSessionManager(ProbeClient(StatusError(503))), id="5xx"),
        pytest.param(
            lambda: FakeSessionManager(ProbeClient(TimeoutError("read timed out"))), id="timeout"
        ),
        pytest.param(
            lambda: FakeSessionManager(error=RuntimeError("no client")),
            id="client-construction-fails",
        ),
        pytest.param(lambda: None, id="no-session-manager"),
    ],
)
async def test_reimport_publication_requires_a_successful_probe(env, monkeypatch, manager):
    await seed_import(env.factory, status="active", job_state="queued", job_kind="reimport")
    cluster = install_cluster(env, monkeypatch)
    upload, file_task = _tasks()

    await _processor("reimport", snapshot="snap-2", session_manager=manager()).process_item(
        upload, "imp-1", file_task
    )

    # an inconclusive or missing probe compensates: the old generation keeps serving, the new one goes
    assert _serving(cluster, 1) and cluster.deleted == _concretes(2)
    imp, _ = await load_import(env.factory)
    assert (imp.status, imp.generation, imp.job_state, imp.pending_publication) == (
        "active",
        1,
        "failed",
        None,
    )
    assert "Could not verify access" in imp.job_error
    assert file_task.status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_reimport_probe_refusal_reports_the_missing_role(env, monkeypatch):
    await seed_import(env.factory, status="active", job_state="queued", job_kind="reimport")
    cluster = install_cluster(env, monkeypatch)
    upload, file_task = _tasks()
    manager = FakeSessionManager(ProbeClient(StatusError(403)))

    await _processor("reimport", snapshot="snap-2", session_manager=manager).process_item(
        upload, "imp-1", file_task
    )

    assert _serving(cluster, 1) and "not readable" in (await load_import(env.factory))[0].job_error


@pytest.mark.asyncio
async def test_reimport_probe_uses_the_effective_client_when_the_raw_token_is_absent(
    env, monkeypatch
):
    """No-auth users have no raw JWT, but the session manager still yields their effective client."""
    await seed_import(env.factory, status="active", job_state="queued", job_kind="reimport")
    cluster = install_cluster(env, monkeypatch)
    manager = FakeSessionManager()
    upload, file_task = _tasks()

    await _processor(
        "reimport", snapshot="snap-2", session_manager=manager, jwt_token=None
    ).process_item(upload, "imp-1", file_task)

    assert manager.requests == [("alice", None)]
    assert manager.client.searches == [_alias(0), _alias(1)]  # every alias, with that client
    assert _serving(cluster, 2) and file_task.status == TaskStatus.COMPLETED


# ── admitted snapshot identity and reserved generation (B12, B5) ─────────


def _replaced_snapshot(env):
    import dataclasses

    async def build_manifest(snapshot_name, indices):
        from ._support import make_manifest

        return dataclasses.replace(
            make_manifest(indices, snapshot=snapshot_name), snapshot_uuid="uuid-recreated"
        )

    env.src.build_manifest = build_manifest


@pytest.mark.asyncio
async def test_initial_import_rejects_a_snapshot_replaced_after_admission_before_staging(env):
    await seed_import(env.factory, status="staging", job_state="queued")  # admitted as uuid-snap-1
    _replaced_snapshot(env)
    upload, file_task = _tasks()

    await _processor().process_item(upload, "imp-1", file_task)

    imp, _ = await load_import(env.factory)
    assert (imp.status, imp.job_state) == ("failed", "failed")
    assert "not the snapshot that was admitted" in imp.job_error
    assert env.store.staged == [] and env.rec.names("register_repository") == []
    assert env.rec.names("restore_index") == []
    assert imp.snapshot_uuid == "uuid-snap-1"  # the registry keeps the admitted identity


@pytest.mark.asyncio
async def test_reimport_rejects_a_snapshot_replaced_after_admission_before_staging(env):
    await seed_import(env.factory, status="active", job_state="queued", job_kind="reimport")
    _replaced_snapshot(env)
    upload, file_task = _tasks()

    await _processor("reimport", snapshot="snap-2", snapshot_uuid="uuid-snap-2").process_item(
        upload, "imp-1", file_task
    )

    imp, _ = await load_import(env.factory)
    assert (imp.status, imp.generation, imp.job_state) == ("active", 1, "failed")
    assert (imp.snapshot_name, imp.snapshot_uuid) == ("snap-1", "uuid-snap-1")
    assert env.store.staged == [] and env.rec.names("restore_index") == []


@pytest.mark.asyncio
async def test_reimport_without_an_admitted_identity_fails_closed(env):
    await seed_import(env.factory, status="active", job_state="queued", job_kind="reimport")
    upload, file_task = _tasks()

    await _processor("reimport", snapshot="snap-2", snapshot_uuid="").process_item(
        upload, "imp-1", file_task
    )

    imp, _ = await load_import(env.factory)
    assert (imp.job_state, imp.generation) == ("failed", 1) and env.store.staged == []


@pytest.mark.asyncio
async def test_reimport_builds_the_generation_reserved_at_admission(env, monkeypatch):
    """B5: a retry after an interrupted attempt must not reuse that attempt's generation."""
    await seed_import(env.factory, status="active", job_state="queued", job_kind="reimport")
    await _set_import(
        env, attempt_generation=3
    )  # attempt 2 was interrupted and may be under cleanup
    cluster = install_cluster(env, monkeypatch)
    upload, file_task = _tasks()

    await _processor("reimport", snapshot="snap-2").process_item(upload, "imp-1", file_task)

    imp, datasets = await load_import(env.factory)
    assert imp.generation == 3 and [d.concrete_index for d in datasets] == _concretes(3)
    assert [c[1] for c in env.rec.names("restore_index")] == _concretes(3)
    assert (SLUG, 3) in env.store.removed and (SLUG, 2) not in env.store.removed
    assert _serving(cluster, 3) and cluster.deleted == _concretes(1)
